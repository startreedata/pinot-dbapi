"""Decode native broker results without DB-API value conversions or policy."""

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import math
from typing import Any, Literal

from pinotdb.exceptions import DataError


_STATISTICS_EXCLUDED_FIELDS = frozenset({
    "resultTable", "exceptions", "traceInfo", "selectionResults",
    "aggregationResults",
})
_LIMIT_FLAGS = (
    "numGroupsLimitReached", "maxRowsInJoinReached", "maxRowsInWindowReached",
    "mseLiteLeafStageLimitReached", "maxRowsInDistinctReached",
    "maxRowsWithoutChangeInDistinctReached",
    "maxExecutionTimeInDistinctReached",
)
_PRIMITIVE_TYPES = frozenset({
    "INT", "LONG", "FLOAT", "DOUBLE", "BOOLEAN", "STRING", "BYTES",
    "TIMESTAMP", "BIG_DECIMAL", "JSON",
})
_MALFORMED = "Pinot returned malformed native query response."


@dataclass
class NativeQueryMetadata:
    """Execution evidence, independent of paging or full dataset coverage."""

    completeness: Literal["complete", "partial", "unknown"] = "unknown"
    servers_queried: int | None = None
    servers_responded: int | None = None
    partial_result: bool | None = None
    execution_limit_reached: bool | None = None
    execution_limit_flags: dict[str, bool] = field(default_factory=dict)
    early_termination_reasons: list[str] = field(default_factory=list)
    query_sha256: str | None = None
    native_query_id: int | str | None = None
    client_query_id: str | None = None
    unknown_reasons: list[str] = field(default_factory=list)


@dataclass
class NativeQueryResult:
    """Native JSON rows, execution evidence, and unconverted broker payload."""

    columns: list[str] = field(default_factory=list)
    column_types: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    metadata: NativeQueryMetadata = field(default_factory=NativeQueryMetadata)
    query_stats: dict[str, Any] = field(default_factory=dict)
    query_statistics: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)


def _is_json(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json(item)
            for key, item in value.items()
        )
    return False


def _matches_type(value: Any, data_type: str) -> bool:
    if value is None:
        return True
    if data_type.endswith("_ARRAY"):
        return isinstance(value, list) and all(
            _matches_type(item, data_type.removesuffix("_ARRAY"))
            for item in value
        )
    if data_type in {"INT", "LONG"}:
        return type(value) is int
    if data_type in {"FLOAT", "DOUBLE"}:
        # Jackson encodes non-finite floating-point values as JSON strings.
        return type(value) in (int, float) or (
            isinstance(value, str) and value in {"Infinity", "-Infinity", "NaN"}
        )
    if data_type == "BOOLEAN":
        return type(value) is bool
    if data_type in {"STRING", "BYTES", "JSON"}:
        return isinstance(value, str)
    if data_type == "TIMESTAMP":
        return type(value) in (str, int)
    if data_type == "BIG_DECIMAL":
        if type(value) not in (str, int, float):
            return False
        try:
            return Decimal(str(value)).is_finite()
        except InvalidOperation:
            return False
    return True


def decode_query_response(
    payload: Any, *, sql: str | None = None,
) -> NativeQueryResult:
    """Validate native JSON, retaining partial results without accepting them.

    Missing execution metadata remains unknown. Affirmative partial evidence
    takes precedence over missing fields. This decoder applies no SQL bounds,
    DB-API conversion, response policy, or network retry. Duplicate aliases are
    preserved by returning row arrays rather than dictionaries.
    """
    try:
        valid_json = isinstance(payload, dict) and _is_json(payload)
    except RecursionError:
        valid_json = False
    if not valid_json:
        raise DataError(_MALFORMED)
    if sql is not None and not isinstance(sql, str):
        raise DataError(_MALFORMED)

    unknown = []
    native_exceptions = payload.get("exceptions")
    if native_exceptions is None:
        unknown.append("exceptions_metadata_missing")
        native_exceptions = []
    elif not isinstance(native_exceptions, list) or not all(
        isinstance(exception, dict) for exception in native_exceptions
    ):
        raise DataError(_MALFORMED)

    servers = []
    for name in ("numServersQueried", "numServersResponded"):
        value = payload.get(name)
        if value is None:
            unknown.append(name + "_missing")
        elif type(value) is not int or value < 0:
            raise DataError(_MALFORMED)
        servers.append(value)
    queried, responded = servers
    if queried is not None and responded is not None and responded > queried:
        raise DataError(_MALFORMED)
    if queried == 0:
        unknown.append("no_server_execution_attested")

    flags = {}
    for name in (*_LIMIT_FLAGS, "partialResult", "isPartialResult"):
        value = payload.get(name)
        if value is not None and type(value) is not bool:
            raise DataError(_MALFORMED)
        flags[name] = value
    if flags["numGroupsLimitReached"] is None:
        unknown.append("group_limit_metadata_missing")
    limit_flags = {
        name: flags[name] for name in _LIMIT_FLAGS if flags[name] is not None
    }
    partial_values = [
        flags[name] for name in ("partialResult", "isPartialResult")
    ]
    partial = any(value is True for value in partial_values)
    partial_flag = (
        partial if any(value is not None for value in partial_values) else None
    )
    early_reasons = payload.get("earlyTerminationReasons", [])
    if not isinstance(early_reasons, list) or not all(
        isinstance(reason, str) and reason for reason in early_reasons
    ):
        raise DataError(_MALFORMED)
    execution_limit = any(limit_flags.values()) or bool(early_reasons)

    columns, column_types, rows = [], [], []
    table = payload.get("resultTable")
    if table is None:
        unknown.append("result_table_missing")
    else:
        if not isinstance(table, dict) or not isinstance(
            table.get("dataSchema"), dict
        ):
            raise DataError(_MALFORMED)
        schema = table["dataSchema"]
        columns = schema.get("columnNames")
        rows = table.get("rows")
        if (
            not isinstance(columns, list) or not columns
            or not all(isinstance(name, str) for name in columns)
            or not isinstance(rows, list)
            or any(
                not isinstance(row, list) or len(row) != len(columns)
                for row in rows
            )
        ):
            raise DataError(_MALFORMED)
        column_types = schema.get("columnDataTypes")
        if column_types is None:
            unknown.append("column_types_missing")
            column_types = []
        elif (
            not isinstance(column_types, list)
            or len(column_types) != len(columns)
            or not all(isinstance(name, str) and name for name in column_types)
        ):
            raise DataError(_MALFORMED)
        if column_types and any(
            not _matches_type(value, data_type)
            for row in rows
            for value, data_type in zip(row, column_types)
        ):
            raise DataError(_MALFORMED)
        if any(
            name.removesuffix("_ARRAY") not in _PRIMITIVE_TYPES
            for name in column_types
        ):
            unknown.append("column_type_not_validated")

    native_id = payload.get("requestId")
    client_id = payload.get("clientRequestId")
    if native_id is not None and type(native_id) not in (int, str):
        raise DataError(_MALFORMED)
    if client_id is not None and not isinstance(client_id, str):
        raise DataError(_MALFORMED)
    incomplete = (
        bool(native_exceptions) or partial or execution_limit
        or (queried is not None and responded is not None
            and responded < queried)
    )
    completeness: Literal["complete", "partial", "unknown"] = (
        "partial" if incomplete else "unknown" if unknown else "complete"
    )
    statistics = {
        name: value for name, value in payload.items()
        if name not in _STATISTICS_EXCLUDED_FIELDS
    }
    return NativeQueryResult(
        columns=list(columns), column_types=list(column_types),
        rows=deepcopy(rows), exceptions=deepcopy(native_exceptions),
        metadata=NativeQueryMetadata(
            completeness=completeness,
            servers_queried=queried, servers_responded=responded,
            partial_result=partial_flag,
            execution_limit_reached=(
                execution_limit if limit_flags or early_reasons else None
            ),
            execution_limit_flags=limit_flags,
            early_termination_reasons=list(early_reasons),
            query_sha256=(hashlib.sha256(sql.encode()).hexdigest()
                          if sql is not None else None),
            native_query_id=native_id, client_query_id=client_id,
            unknown_reasons=unknown,
        ),
        query_stats={
            name: value for name, value in statistics.items()
            if not isinstance(value, (dict, list))
        },
        query_statistics=deepcopy(statistics), raw_response=deepcopy(payload),
    )
