import asyncio
import os

from pinotdb import NativeQueryResult, connect, connect_async


def test_native_sync_async_cursor_results_against_quickstart():
    configuration = {
        "host": os.getenv("PINOT_HOST", "localhost"),
        "port": int(os.getenv("PINOT_BROKER_PORT", "8000")),
    }
    query = "SELECT count(*) FROM baseballStats LIMIT 1"
    connection = connect(**configuration)
    try:
        cursor = connection.cursor()
        result = cursor.execute_native(query, allow_partial=True)
        assert cursor.native_result is result
        assert cursor.query_statistics == result.query_statistics
    finally:
        connection.close()

    async def query_async():
        connection = connect_async(**configuration)
        try:
            cursor = connection.cursor()
            return await cursor.execute_native(query, allow_partial=True)
        finally:
            await connection.close()

    async_result = asyncio.run(query_async())
    for native_result in (result, async_result):
        assert isinstance(native_result, NativeQueryResult)
        assert native_result.exceptions == []
        assert len(native_result.columns) == 1
        assert len(native_result.column_types) == 1
        assert int(native_result.rows[0][0]) > 0
        assert native_result.metadata.servers_queried > 0
        assert (
            native_result.metadata.servers_responded
            == native_result.metadata.servers_queried
        )
        assert native_result.raw_response["resultTable"]["rows"] == (
            native_result.rows)
        assert native_result.metadata.query_sha256
    assert result.rows == async_result.rows
