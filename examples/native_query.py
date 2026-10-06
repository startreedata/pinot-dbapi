"""Inspect native results from the baseballStats quickstart, sync or async."""

import argparse
import asyncio

import httpx

from pinotdb import NativeQueryResult, connect, connect_async


SQL = (
    "SELECT playerID, yearID FROM baseballStats "
    "WHERE yearID >= %(year)s LIMIT 5"
)
PARAMETERS = {"year": 2010}


def show_evidence(result: NativeQueryResult) -> None:
    print("Execution:", result.metadata.completeness)
    print("Columns:", result.columns)
    print("Returned rows:", len(result.rows))
    print("Query errors:", len(result.exceptions))
    print("Execution limits:", result.metadata.execution_limit_flags)
    print("Unknown evidence:", result.metadata.unknown_reasons)
    print("Stage statistics available:",
          "stageStats" in result.query_statistics)
    # result.raw_response preserves the complete native JSON payload.
    # Use result.rows only after checking completeness and exceptions.


def run_sync() -> None:
    with connect(host="localhost", port=8000) as cursor:
        result = cursor.execute_native(
            SQL, PARAMETERS,
            query_options="timeoutMs=4000;clientQueryId=example-native-sync",
            timeout=httpx.Timeout(5.0, connect=1.0),
            allow_partial=True,
        )
        show_evidence(result)


async def run_async() -> None:
    async with connect_async(host="localhost", port=8000) as cursor:
        result = await cursor.execute_native(
            SQL, PARAMETERS,
            query_options="timeoutMs=4000;clientQueryId=example-native-async",
            timeout=httpx.Timeout(5.0, connect=1.0),
            allow_partial=True,
        )
        show_evidence(result)


def run_main() -> None:
    """Run the sync example when called by the integration example runner."""
    run_sync()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--async", dest="use_async", action="store_true",
        help="Use the async cursor instead of the sync cursor.",
    )
    arguments = parser.parse_args()
    if arguments.use_async:
        asyncio.run(run_async())
    else:
        run_main()
