"""Native decoding preserves broker evidence independently of DB-API policy."""

from copy import deepcopy
import hashlib

import pytest

from pinotdb.exceptions import DataError
from pinotdb.native import decode_query_response


@pytest.fixture
def payload():
    return {
        "resultTable": {
            "dataSchema": {
                "columnNames": ["value"], "columnDataTypes": ["LONG"],
            },
            "rows": [[7]],
        },
        "exceptions": [], "numServersQueried": 2, "numServersResponded": 2,
        "numGroupsLimitReached": False, "requestId": 123,
        "clientRequestId": "query-123", "timeUsedMs": 9,
    }


def test_empty_complete_result_preserves_schema_and_ids(payload):
    payload["resultTable"]["rows"] = []
    sql = "SELECT value FROM example WHERE value < 0"
    result = decode_query_response(payload, sql=sql)
    assert result.columns == ["value"]
    assert result.column_types == ["LONG"]
    assert result.rows == []
    assert result.metadata.completeness == "complete"
    assert result.metadata.query_sha256 == (
        hashlib.sha256(sql.encode()).hexdigest()
    )
    assert result.metadata.native_query_id == 123
    assert result.metadata.client_query_id == "query-123"


def test_nested_and_future_statistics_are_preserved_without_rows(payload):
    payload.update({
        "stageStats": {"1": {"operators": [{"cpuNs": 30}]}},
        "streamStatsCoverage": [{"complete": False}],
        "responseMetadata": {"futureMetric": {"samples": [1, 2]}},
        "tablesQueried": ["example"], "pools": ["pool-a"],
        "futureNullable": None,
        "futureScalar": "native-value", "futureCounter": 99,
        "traceInfo": {"server": "trace"},
    })
    result = decode_query_response(payload)
    for name in (
        "stageStats", "streamStatsCoverage", "responseMetadata",
        "tablesQueried", "pools",
    ):
        assert result.query_statistics[name] == payload[name]
        assert name not in result.query_stats
    assert result.query_stats["futureScalar"] == "native-value"
    assert result.query_stats["futureCounter"] == 99
    assert result.query_stats["futureNullable"] is None
    assert result.query_statistics["requestId"] == 123
    for name in ("resultTable", "exceptions", "traceInfo"):
        assert name not in result.query_statistics
        assert name not in result.query_stats
    assert result.raw_response == payload


@pytest.mark.parametrize("aggregate_partial", [None, False])
@pytest.mark.parametrize("flag", [
    "numGroupsLimitReached", "maxRowsInJoinReached", "maxRowsInWindowReached",
    "mseLiteLeafStageLimitReached", "maxRowsInDistinctReached",
    "maxRowsWithoutChangeInDistinctReached",
    "maxExecutionTimeInDistinctReached",
])
def test_native_limit_proof_overrides_aggregate_false_or_absence(
    payload, flag, aggregate_partial,
):
    payload[flag] = True
    if aggregate_partial is not None:
        payload["partialResult"] = aggregate_partial
    result = decode_query_response(payload)
    assert result.rows == [[7]]
    assert result.metadata.completeness == "partial"
    assert result.metadata.execution_limit_reached is True
    assert result.metadata.execution_limit_flags[flag] is True


def test_future_early_reason_remains_native_partial_evidence(payload):
    payload["earlyTerminationReasons"] = ["DISTINCT_MAX_ROWS", "FUTURE_REASON"]
    payload["partialResult"] = False
    payload.pop("numGroupsLimitReached")
    result = decode_query_response(payload)
    assert result.metadata.completeness == "partial"
    assert result.metadata.early_termination_reasons == [
        "DISTINCT_MAX_ROWS", "FUTURE_REASON",
    ]
    assert result.query_statistics["earlyTerminationReasons"] == [
        "DISTINCT_MAX_ROWS", "FUTURE_REASON",
    ]
    assert "group_limit_metadata_missing" in result.metadata.unknown_reasons


@pytest.mark.parametrize("responded", [1, 2])
def test_server_shortfall_and_errors_are_retained_as_partial(
    payload, responded,
):
    payload["numServersResponded"] = responded
    payload["exceptions"] = [{"errorCode": 200, "message": "native error"}]
    result = decode_query_response(payload)
    assert result.metadata.completeness == "partial"
    assert result.exceptions == payload["exceptions"]
    assert result.rows == [[7]]


@pytest.mark.parametrize("missing", [
    "resultTable", "exceptions", "numServersQueried", "numServersResponded",
    "numGroupsLimitReached",
])
def test_missing_evidence_stays_unknown(payload, missing):
    payload.pop(missing)
    result = decode_query_response(payload)
    assert result.metadata.completeness == "unknown"
    assert result.metadata.unknown_reasons


def test_missing_column_types_and_broker_local_query_are_unknown(payload):
    payload["resultTable"]["dataSchema"].pop("columnDataTypes")
    payload["numServersQueried"] = payload["numServersResponded"] = 0
    result = decode_query_response(payload)
    assert result.rows == [[7]]
    assert result.column_types == []
    assert result.metadata.completeness == "unknown"
    assert "column_types_missing" in result.metadata.unknown_reasons
    assert "no_server_execution_attested" in result.metadata.unknown_reasons


def test_duplicate_aliases_remain_legal_array_results(payload):
    payload["resultTable"] = {
        "dataSchema": {
            "columnNames": ["value", "value"],
            "columnDataTypes": ["LONG", "STRING"],
        },
        "rows": [[7, "seven"]],
    }
    result = decode_query_response(payload)
    assert result.columns == ["value", "value"]
    assert result.rows == [[7, "seven"]]
    assert result.metadata.completeness == "complete"


@pytest.mark.parametrize("data_type,value", [
    ("TIMESTAMP", "2026-10-06 00:00:00.000"), ("BYTES", "abff"),
    ("BIG_DECIMAL", "1.250"), ("BIG_DECIMAL", 1.25),
    ("JSON", '{"native": [1, true]}'),
    ("LONG_ARRAY", [1, None, 3]),
    ("FLOAT", "Infinity"), ("DOUBLE", "-Infinity"),
    ("FLOAT_ARRAY", ["NaN", "-Infinity"]),
    ("DOUBLE_ARRAY", ["Infinity", "-Infinity", "NaN"]),
])
def test_native_values_remain_json_without_dbapi_conversion(
    payload, data_type, value,
):
    payload["resultTable"]["dataSchema"]["columnDataTypes"] = [data_type]
    payload["resultTable"]["rows"] = [[value]]
    original = deepcopy(payload)
    result = decode_query_response(payload)
    assert payload == original
    assert result.raw_response == original
    assert result.rows == [[value]]
    assert result.metadata.completeness == "complete"
    result.rows[0][0] = "changed"
    payload["resultTable"]["rows"][0][0] = "also changed"
    assert result.raw_response == original


def test_unknown_native_type_preserves_json_as_unknown(payload):
    payload["resultTable"]["dataSchema"]["columnDataTypes"] = ["FUTURE_TYPE"]
    payload["resultTable"]["rows"] = [[{"native": [1, True]}]]
    result = decode_query_response(payload)
    assert result.rows == [[{"native": [1, True]}]]
    assert result.metadata.completeness == "unknown"
    assert "column_type_not_validated" in result.metadata.unknown_reasons


@pytest.mark.parametrize("field,value", [
    ("numServersQueried", True), ("numServersResponded", "2"),
    ("numServersQueried", -1), ("numServersResponded", 3),
    ("numGroupsLimitReached", 0), ("maxRowsInJoinReached", "true"),
    ("maxRowsInWindowReached", 1), ("mseLiteLeafStageLimitReached", []),
    ("maxRowsInDistinctReached", "false"),
    ("maxRowsWithoutChangeInDistinctReached", 0),
    ("maxExecutionTimeInDistinctReached", 1), ("partialResult", "false"),
    ("earlyTerminationReasons", "DISTINCT_MAX_ROWS"),
    ("earlyTerminationReasons", [0]), ("exceptions", [{}, 1]),
    ("requestId", False), ("clientRequestId", 123),
    ("futureCounter", float("inf")),
])
def test_malformed_metadata_fails_without_echoing_response(
    payload, field, value,
):
    payload[field] = value
    with pytest.raises(DataError, match="malformed native query response"):
        decode_query_response(payload)


@pytest.mark.parametrize("rows", [[[]], [[7, 8]], [{"value": 7}], [[True]]])
def test_malformed_width_shape_or_cell_type_fails(payload, rows):
    payload["resultTable"]["rows"] = rows
    with pytest.raises(DataError):
        decode_query_response(payload)


@pytest.mark.parametrize("data_type,value", [
    ("STRING", 7), ("BOOLEAN", 1), ("LONG_ARRAY", ["one"]),
    ("BIG_DECIMAL", "NaN"), ("DOUBLE", float("nan")),
    ("JSON", {"native": True}),
    ("FLOAT", True), ("DOUBLE", "1.25"),
    ("DOUBLE_ARRAY", ["NaN", "invalid"]),
])
def test_malformed_primitive_types_fail(payload, data_type, value):
    payload["resultTable"]["dataSchema"]["columnDataTypes"] = [data_type]
    payload["resultTable"]["rows"] = [[value]]
    with pytest.raises(DataError):
        decode_query_response(payload)
