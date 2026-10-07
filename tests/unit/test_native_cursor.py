import asyncio
from copy import deepcopy
from datetime import datetime
import json
from unittest.mock import patch

import httpx
import pytest

from pinotdb import (
    NativeQueryMetadata, NativeQueryResult, connect, connect_async, db,
    exceptions,
)


def native_payload(**overrides):
    payload = {
        "resultTable": {
            "dataSchema": {
                "columnNames": ["eventTs", "details"],
                "columnDataTypes": ["TIMESTAMP", "STRING"],
            },
            "rows": [["2026-10-06 00:00:00.0", '{"source":"span"}']],
        },
        "exceptions": [],
        "numServersQueried": 1,
        "numServersResponded": 1,
        "numGroupsLimitReached": False,
        "partialResult": False,
        "timeUsedMs": 7,
        "stageStats": {"0": {"numBlocks": 2}},
        "traceInfo": {"server": "s1"},
    }
    payload.update(overrides)
    return payload


def run(cursor, method, *args, **kwargs):
    result = getattr(cursor, method)(*args, **kwargs)
    if isinstance(cursor, db.AsyncCursor):
        return asyncio.run(result)
    return result


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def cursor_factory(request):
    clients = []
    calls = []
    async_mode = request.param

    def create(payload=None, status_code=200, **kwargs):
        body = native_payload() if payload is None else payload

        def respond(http_request):
            calls.append(http_request)
            return httpx.Response(status_code, json=body)

        client_type = httpx.AsyncClient if async_mode else httpx.Client
        client = client_type(transport=httpx.MockTransport(respond))
        clients.append(client)
        cls = db.AsyncCursor if async_mode else db.Cursor
        return cls(host="broker", session=client, **kwargs), calls

    yield create
    for client in clients:
        if async_mode:
            asyncio.run(client.aclose())
        else:
            client.close()


def test_native_rows_and_statistics_remain_unconverted(cursor_factory):
    cursor, calls = cursor_factory()
    result = run(
        cursor, "execute_native", "SELECT eventTs, details FROM spans")

    assert isinstance(result, NativeQueryResult)
    assert isinstance(result.metadata, NativeQueryMetadata)
    assert result.metadata.completeness == "complete"
    assert result.columns == ["eventTs", "details"]
    assert result.column_types == ["TIMESTAMP", "STRING"]
    assert result.rows == native_payload()["resultTable"]["rows"]
    assert result.metadata.query_sha256
    assert cursor.native_result is result
    assert cursor.query_stats["timeUsedMs"] == 7
    assert "stageStats" not in cursor.query_stats
    assert cursor.query_statistics["stageStats"] == {"0": {"numBlocks": 2}}
    assert "traceInfo" not in cursor.query_statistics
    assert "resultTable" not in cursor.query_statistics
    assert "exceptions" not in cursor.query_statistics
    assert cursor.raw_query_response["response"] == native_payload()
    assert len(calls) == 1
    with pytest.raises(exceptions.Error, match="before `execute`"):
        cursor.fetchone()


def test_compatibility_views_do_not_alias_native_evidence(cursor_factory):
    cursor, _ = cursor_factory()
    result = run(
        cursor, "execute_native", "SELECT eventTs, details FROM spans")
    original_response = deepcopy(result.raw_response)
    original_statistics = deepcopy(result.query_statistics)
    original_stats = dict(result.query_stats)

    cursor.raw_query_response["response"]["resultTable"]["rows"][0][0] = 99
    cursor.query_statistics["stageStats"]["0"]["numBlocks"] = 99
    cursor.query_stats["numServersResponded"] = 99

    assert result.raw_response == original_response
    assert result.query_statistics == original_statistics
    assert result.query_stats == original_stats
    assert result.metadata.servers_responded == 1
    assert cursor.native_result is result


def test_request_configuration_on_single_submission(cursor_factory):
    cursor, calls = cursor_factory(
        scheme="https", port=443, path="/query", username="user",
        password="pass", database="telemetry", use_multistage_engine=True,
        query_options="maxRowsInJoin=8",
    )
    timeout = httpx.Timeout(connect=1, read=2, write=3, pool=4)
    run(
        cursor, "execute_native", "SELECT * FROM spans WHERE service=%(s)s",
        {"s": "it's"}, query_options="timeoutMs=500",
        timeout=timeout, headers={"X-Request-Id": "req-1"},
    )

    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == "https://broker/query"
    assert request.headers["database"] == "telemetry"
    assert request.headers["x-request-id"] == "req-1"
    assert request.headers["authorization"] == "Basic dXNlcjpwYXNz"
    assert request.headers["x-correlation-id"]
    assert request.extensions["timeout"] == timeout.as_dict()
    assert json.loads(request.content) == {
        "sql": "SELECT * FROM spans WHERE service='it''s'",
        "queryOptions": (
            "timeoutMs=500;maxRowsInJoin=8;useMultistageEngine=true"),
    }


def test_per_call_auth_and_correlation_override_are_honored(cursor_factory):
    cursor, calls = cursor_factory(username="configured", password="pass")
    run(
        cursor, "execute_native", "SELECT * FROM spans",
        auth=("per-call", "secret"),
        headers={"X-Correlation-Id": "request-owner"},
    )
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Basic cGVyLWNhbGw6c2VjcmV0"
    assert calls[0].headers.get_list("x-correlation-id") == ["request-owner"]


@pytest.mark.parametrize("changes", [
    {"partialResult": True},
    {"numServersQueried": 2},
    {"numGroupsLimitReached": True},
    {"exceptions": [{"errorCode": 400, "message": "SQL failed"}]},
])
def test_default_policy_preserves_evidence_before_raising(
        cursor_factory, changes):
    cursor, calls = cursor_factory(native_payload(**changes))
    with pytest.raises(exceptions.DatabaseError) as raised:
        run(cursor, "execute_native", "SELECT * FROM spans")

    result = raised.value.native_result
    assert result is cursor.native_result
    assert result.metadata.completeness == "partial"
    assert cursor.query_stats["timeUsedMs"] == 7
    assert cursor.query_statistics["stageStats"] == {"0": {"numBlocks": 2}}
    assert cursor.raw_query_response["response"] == native_payload(**changes)
    assert len(calls) == 1


def test_unknown_requires_explicit_caller_policy(cursor_factory):
    payload = native_payload()
    del payload["numGroupsLimitReached"]
    cursor, calls = cursor_factory(payload)
    with pytest.raises(exceptions.DatabaseError) as raised:
        run(cursor, "execute_native", "SELECT * FROM spans")
    assert raised.value.native_result.metadata.completeness == "unknown"
    result = run(
        cursor, "execute_native", "SELECT * FROM spans", allow_partial=True)
    assert result.metadata.completeness == "unknown"
    assert result.metadata.unknown_reasons
    assert len(calls) == 2


def test_allow_partial_returns_native_sql_errors_without_ignoring_them(
        cursor_factory):
    errors = [{"errorCode": 400, "message": "SQL failed"}]
    cursor, calls = cursor_factory(
        native_payload(exceptions=errors), ignore_exception_error_codes="400")
    result = run(
        cursor, "execute_native", "SELECT * FROM spans", allow_partial=True)
    assert result.exceptions == errors
    assert result.metadata.completeness == "partial"
    assert len(calls) == 1


def test_http_failure_keeps_raw_stats_but_raises_httpx_error(cursor_factory):
    cursor, calls = cursor_factory(native_payload(), status_code=503)
    with pytest.raises(httpx.HTTPStatusError) as raised:
        run(
            cursor, "execute_native", "SELECT * FROM spans",
            allow_partial=True)
    assert raised.value.response.status_code == 503
    assert cursor.raw_query_response["status_code"] == 503
    assert cursor.query_stats["timeUsedMs"] == 7
    assert cursor.query_statistics["stageStats"] == {"0": {"numBlocks": 2}}
    assert cursor.native_result is None
    assert len(calls) == 1


def test_malformed_schema_is_not_hidden_by_allow_partial(cursor_factory):
    payload = native_payload()
    payload["resultTable"]["rows"] = [["only-one-column"]]
    cursor, calls = cursor_factory(payload)
    with pytest.raises(exceptions.DataError, match="malformed"):
        run(
            cursor, "execute_native", "SELECT * FROM spans",
            allow_partial=True)
    assert cursor.query_stats["timeUsedMs"] == 7
    assert cursor.raw_query_response["response"] == payload
    assert cursor.native_result is None
    assert len(calls) == 1


@pytest.mark.parametrize("status_code", [200, 503])
def test_non_json_response_has_expected_transport_or_data_error(
        cursor_factory, status_code):
    cursor, _ = cursor_factory()
    response = httpx.Response(
        status_code, text="invalid-json",
        request=httpx.Request("POST", cursor.url),
    )
    error_type = (
        exceptions.DataError if status_code == 200 else httpx.HTTPStatusError)
    with patch.object(cursor.session, "post", return_value=response) as post:
        with pytest.raises(error_type):
            run(cursor, "execute_native", "SELECT * FROM spans")
    assert post.call_count == 1
    assert cursor.raw_query_response == {
        "response": "invalid-json", "status_code": status_code}
    assert cursor.query_stats == {}
    assert cursor.query_statistics == {}
    assert cursor.native_result is None


def test_failure_clears_previous_query_evidence(cursor_factory):
    cursor, calls = cursor_factory()
    run(cursor, "execute_native", "SELECT * FROM spans")
    with patch.object(
            cursor.session, "post", side_effect=httpx.ReadTimeout("late")):
        with pytest.raises(httpx.ReadTimeout):
            run(cursor, "execute_native", "SELECT * FROM spans")
    assert cursor.native_result is None
    assert cursor.raw_query_response is None
    assert cursor.query_stats == {}
    assert cursor.query_statistics == {}
    assert cursor.timeUsedMs == -1
    assert cursor.schema is None
    assert len(calls) == 1


def test_legacy_attempt_also_clears_prior_native_evidence(cursor_factory):
    cursor, _ = cursor_factory()
    run(cursor, "execute_native", "SELECT * FROM spans")
    with patch.object(
            cursor.session, "post", side_effect=httpx.ReadTimeout("late")):
        with pytest.raises(httpx.ReadTimeout):
            run(cursor, "execute", "SELECT * FROM spans")
    assert cursor.native_result is None
    assert cursor.raw_query_response is None
    assert cursor.query_stats == {}
    assert cursor.query_statistics == {}


def test_legacy_fetch_conversion_keeps_original_response(cursor_factory):
    payload = native_payload()
    payload["resultTable"]["dataSchema"]["columnDataTypes"] = [
        "TIMESTAMP", "JSON"]
    original = deepcopy(payload)
    cursor, _ = cursor_factory(payload)
    run(cursor, "execute", "SELECT eventTs, details FROM spans")
    rows = cursor.fetchall()
    assert rows == [[datetime(2026, 10, 6), {"source": "span"}]]
    assert cursor.raw_query_response["response"] == original
    assert cursor.query_statistics["stageStats"] == original["stageStats"]
    assert cursor.native_result is None
    run(
        cursor, "execute_native", "SELECT eventTs, details FROM spans",
        allow_partial=True)
    assert cursor.native_result.rows == original["resultTable"]["rows"]


def test_legacy_fetch_without_conversion_keeps_original_row_containers(
        cursor_factory):
    payload = native_payload()
    payload["resultTable"] = {
        "dataSchema": {"columnNames": ["n"], "columnDataTypes": ["INT"]},
        "rows": [[1], [2]],
    }
    cursor, _ = cursor_factory(payload)
    run(cursor, "execute", "SELECT n FROM spans")
    first = cursor.fetchone()
    first[0] = 99
    assert cursor.fetchall() == [[2]]
    assert cursor.raw_query_response["response"]["resultTable"]["rows"] == [
        [1], [2]]


@pytest.mark.parametrize("async_mode", [False, True])
def test_connection_honors_tls_when_creating_native_cursor(async_mode):
    connection_type = connect_async if async_mode else connect
    client_name = "AsyncClient" if async_mode else "Client"
    with patch("pinotdb.db.httpx." + client_name) as client:
        connection = connection_type(
            host="broker", verify_ssl=False, timeout=3)
        connection.cursor()
    client.assert_called_once_with(verify=False, timeout=3.0)
