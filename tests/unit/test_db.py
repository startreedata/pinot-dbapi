import datetime
import uuid
from typing import Any, Dict, Optional
from unittest import TestCase
from unittest.mock import ANY, MagicMock, patch

import httpx

try:
    from unittest import IsolatedAsyncioTestCase
except ImportError:
    from mock.backports import IsolatedAsyncioTestCase

try:
    from unittest.mock import AsyncMock
except ImportError:
    from mock import AsyncMock

from pinotdb import db, exceptions


class ConnectionTest(TestCase):
    def test_starts_without_session_by_default(self):
        connection = db.Connection()

        self.assertIsNone(connection.session)
        self.assertFalse(connection.is_session_external)

    def test_verifies_httpx_session_upon_initializing_if_provided(self):
        client = httpx.Client()

        connection = db.Connection(session=client)

        self.assertIs(connection.session, client)
        self.assertTrue(connection.is_session_external)

    def test_verifies_httpx_session(self):
        client = httpx.Client()
        connection = db.Connection()
        connection.session = client

        connection.verify_session()
        # All good, no errors.

    def test_verifies_timeout_kwargs(self):
        connection = db.Connection(host='localhost', timeout=100)
        cursor = connection.cursor()

        self.assertDictEqual(
            connection.session.timeout.as_dict(), 
            {'connect': 100.0, 'read': 100.0, 'write': 100.0, 'pool': 100.0}
            )
        
        

    def test_fails_to_verify_session_if_unexpected_type(self):
        connection = db.Connection()
        connection.session = object()

        with self.assertRaises(AssertionError):
            connection.verify_session()

    def test_bypasses_verification_if_no_session_initialized(self):
        connection = db.Connection()

        connection.verify_session()

    def test_gets_cursor_from_connection(self):
        connection = db.Connection(host='localhost')

        cursor = connection.cursor()

        self.assertIsInstance(cursor, db.Cursor)

    def test_gets_cursor_from_connection_with_explicit_session(self):
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))
        connection.session.is_closed = False

        cursor = connection.cursor()

        self.assertIsInstance(cursor, db.Cursor)

    def test_renews_session_if_closed_when_getting_cursor(self):
        connection = db.Connection(host='localhost')
        connection.cursor()
        session1 = connection.session

        session1.close()
        connection.cursor()
        session2 = connection.session

        self.assertIsNot(session1, session2)

    def test_cursor_doesnt_close_session_for_other_cursors(self):
        connection = db.Connection(host='localhost')
        cursor1 = connection.cursor()
        cursor2 = connection.cursor()
        cursor1.close()

        self.assertFalse(cursor2.session.is_closed)

    def test_starts_not_closed(self):
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))
        cursor = connection.cursor()

        self.assertFalse(connection.closed)
        self.assertFalse(cursor.closed)

    def test_closes_connection(self):
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))
        cursor = connection.cursor()

        connection.close()

        self.assertTrue(connection.closed)
        self.assertTrue(cursor.closed)

    def test_closes_connection_even_if_cursor_already_closed(self):
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))
        cursor = connection.cursor()
        cursor.close()

        connection.close()

        self.assertTrue(connection.closed)
        self.assertTrue(cursor.closed)

    def test_closes_underlying_session_as_well(self):
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))
        # Just to simulate an implicitly created session.
        connection.is_session_external = False

        connection.close()

        self.assertTrue(connection.session.close.called)

    def test_cant_close_connection_twice(self):
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))

        connection.close()

        with self.assertRaises(exceptions.Error):
            connection.close()

    def test_commits_nothing(self):
        """
        This is just a sanity test, to make sure we follow the expected
        interface.
        """
        connection = db.Connection()

        connection.commit()

    def test_executes_a_statement(self):
        """
        This test tests whether the library is capable of executing statements
        against Pinot by sending requests to it via its API endpoints.

        With this test we're not yet focusing on how the request format or
        anything like that, since it's not the Connection's responsibility to
        do that.
        """
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))
        connection.session.is_closed = False
        response = connection.session.post.return_value
        response.json.return_value = {
            'numServersResponded': 1,
            'numServersQueried': 1,
        }
        response.status_code = 200

        cursor = connection.execute('some statement')

        self.assertIsInstance(cursor, db.Cursor)

    def test_uses_cursor_in_context_manager_block(self):
        connection = db.Connection(
            host='localhost', session=MagicMock(spec=httpx.Client))
        connection.session.is_closed = False

        with connection as cursor:
            self.assertIsInstance(cursor, db.Cursor)
            self.assertFalse(cursor.closed)

        self.assertTrue(cursor.closed)

    def test_connects_sync_via_function(self):
        connection = db.connect(
            host='localhost', session=MagicMock(spec=httpx.Client))

        self.assertIsInstance(connection, db.Connection)


class AsyncConnectionTest(IsolatedAsyncioTestCase):
    def test_starts_without_session_by_default(self):
        connection = db.AsyncConnection()

        self.assertIsNone(connection.session)
        self.assertFalse(connection.is_session_external)

    def test_verifies_httpx_session_upon_initializing_if_provided(self):
        client = httpx.AsyncClient()

        connection = db.AsyncConnection(session=client)

        self.assertIs(connection.session, client)
        self.assertTrue(connection.is_session_external)

    def test_verifies_httpx_session(self):
        client = httpx.AsyncClient()
        connection = db.AsyncConnection()
        connection.session = client

        connection.verify_session()
        # All good, no errors.

    def test_fails_to_verify_session_if_unexpected_type(self):
        connection = db.AsyncConnection()
        connection.session = object()

        with self.assertRaises(AssertionError):
            connection.verify_session()

    def test_bypasses_verification_if_no_session_initialized(self):
        connection = db.AsyncConnection()

        connection.verify_session()

    async def test_uses_cursor_in_context_manager_block(self):
        connection = db.AsyncConnection(
            host='localhost', session=MagicMock(spec=httpx.AsyncClient))
        connection.session.is_closed = False

        async with connection as cursor:
            self.assertIsInstance(cursor, db.AsyncCursor)
            self.assertFalse(cursor.closed)

        self.assertTrue(cursor.closed)

    async def test_cursor_doesnt_close_session_for_other_cursors(self):
        connection = db.AsyncConnection(host='localhost')
        cursor1 = connection.cursor()
        cursor2 = connection.cursor()
        await cursor1.close()

        self.assertFalse(cursor2.session.is_closed)

    async def test_renews_session_if_closed_when_getting_cursor(self):
        connection = db.AsyncConnection(host='localhost')
        connection.cursor()
        session1 = connection.session

        await session1.aclose()
        connection.cursor()
        session2 = connection.session

        self.assertIsNot(session1, session2)

    async def test_closes_connection_even_if_cursor_already_closed(self):
        connection = db.AsyncConnection(
            host='localhost', session=MagicMock(spec=httpx.AsyncClient))
        cursor = connection.cursor()
        await cursor.close()

        await connection.close()

        self.assertTrue(connection.closed)
        self.assertTrue(cursor.closed)

    async def test_closes_underlying_session_as_well(self):
        connection = db.AsyncConnection(
            host='localhost', session=MagicMock(spec=httpx.AsyncClient))
        # Just to simulate an implicitly created session.
        connection.is_session_external = False

        await connection.close()

        self.assertTrue(connection.session.aclose.called)

    async def test_executes_a_statement(self):
        """
        This test tests whether the library is capable of executing statements
        against Pinot by sending requests to it via its API endpoints.

        With this test we're not yet focusing on the request format or
        anything like that, since it's not the Connection's responsibility to
        do that.
        """
        connection = db.AsyncConnection(
            host='localhost', session=AsyncMock(spec=httpx.AsyncClient))
        connection.session.is_closed = False
        response = connection.session.post.return_value
        response.json = MagicMock()
        response.json.return_value = {
            'numServersResponded': 1,
            'numServersQueried': 1,
        }
        response.status_code = 200

        cursor = await connection.execute('some statement')

        self.assertIsInstance(cursor, db.AsyncCursor)

    def test_connects_async_via_function(self):
        connection = db.connect_async()

        self.assertIsInstance(connection, db.AsyncConnection)


class CursorTest(TestCase):
    def create_cursor(
            self, result_table: Optional[Dict[str, Any]] = None,
            status_code: int = 200, debug: bool = False,
            extra_payload: Optional[Dict[str, Any]] = None,
            username: Optional[str] = None,
            password: Optional[str] = None,
            preserve_types: bool = False,
            use_multistage_engine: bool = False,
    ) -> db.Cursor:
        cursor = db.Cursor(
            host='localhost', session=MagicMock(spec=httpx.Client),
            debug=debug, username=username, password=password,
            preserve_types=preserve_types,
            use_multistage_engine=use_multistage_engine,
        )
        cursor.session.is_closed = False
        response = cursor.session.post.return_value
        payload = {
            'numServersResponded': 1,
            'numServersQueried': 1,
        }
        if result_table is not None:
            payload['resultTable'] = result_table
        if extra_payload:
            payload.update(extra_payload)
        response.json.return_value = payload
        response.status_code = status_code
        return cursor

    def test_instantiates_with_basic_url(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        self.assertEqual(cursor.url, 'http://localhost:8099/query/sql')

    def test_instantiates_with_auth(self):
        cursor = db.Cursor(
            host='localhost', session=httpx.Client(),
            username='john', password='my-pass')

        self.assertIsInstance(cursor.auth, httpx.DigestAuth)

    def test_instantiates_with_extra_headers(self):
        cursor = db.Cursor(
            host='localhost', session=httpx.Client(),
            extra_request_headers='foo=bar,baz=yo,Authorization=Bearer foo=')

        self.assertEqual(cursor.session.headers['foo'], 'bar')
        self.assertEqual(cursor.session.headers['baz'], 'yo')
        self.assertEqual(cursor.session.headers['Authorization'], 'Bearer foo=')

    def test_checks_valid_exception_if_not_containing_error_code(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        self.assertTrue(cursor.is_valid_exception({}))

    def test_checks_valid_exception_if_error_code_not_ignored(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        self.assertTrue(cursor.is_valid_exception({
            'errorCode': 123,
        }))

    def test_checks_invalid_exception_if_error_code_ignored(self):
        cursor = db.Cursor(
            host='localhost', session=httpx.Client(),
            ignore_exception_error_codes='123,234')

        self.assertFalse(cursor.is_valid_exception({
            'errorCode': 123,
        }))

    def test_cant_close_connection_twice(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        cursor.close()

        with self.assertRaises(exceptions.Error):
            cursor.close()

    def test_doesnt_close_underlying_session_as_well(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        cursor.close()

        self.assertFalse(cursor.session.is_closed)

    def test_bypasses_session_close_if_already_closed(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())
        cursor.session.close()

        cursor.close()

    def test_checks_sufficient_responded_0_queried_0_responded(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        cursor.check_sufficient_responded('foo', 0, 0)

    def test_checks_sufficient_responded_min1_queried_min1_responded(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        with self.assertRaises(exceptions.DatabaseError):
            cursor.check_sufficient_responded('foo', -1, -1)

    def test_checks_sufficient_responded_3_queried_3_responded(self):
        cursor = db.Cursor(host='localhost', session=httpx.Client())

        cursor.check_sufficient_responded('foo', 3, 3)

    def test_checks_sufficient_responded_5_queried_3_responded(self):
        cursor = db.Cursor(
            host='localhost', session=httpx.Client(),
            acceptable_respond_fraction=2)

        cursor.check_sufficient_responded('foo', 5, 3)

    def test_checks_sufficient_responded_4_queried_half_responded(self):
        cursor = db.Cursor(
            host='localhost', session=httpx.Client(),
            acceptable_respond_fraction=0.5)

        cursor.check_sufficient_responded('foo', 4, 2)

    def test_checks_sufficient_responded_but_zero_needed(self):
        cursor = db.Cursor(
            host='localhost', session=httpx.Client(),
            acceptable_respond_fraction=0)

        cursor.check_sufficient_responded('foo', 10, 0)

    def test_does_not_allow_fetching_if_not_executed_yet(self):
        cursor = db.Cursor(
            host='localhost', session=httpx.Client())

        with self.assertRaises(exceptions.Error):
            cursor.fetchone()

    def test_executes_query_within_session_with_empty_results(self):
        cursor = self.create_cursor()

        cursor.execute('some statement')

        results = list(iter(cursor))
        self.assertEqual(results, [])
        cursor.session.post.assert_called_once_with(
            'http://localhost:8099/query/sql', json={'sql': 'some statement'},
            headers=ANY)

    def test_executes_query_within_session_with_query_options(self):
        cursor = self.create_cursor()

        cursor.execute('some statement', queryOptions={'foo': 'bar'})

        results = list(iter(cursor))
        self.assertEqual(results, [])
        cursor.session.post.assert_called_once_with(
            'http://localhost:8099/query/sql', json={
                'sql': 'some statement', 'queryOptions': {'foo': 'bar'}},
            headers=ANY)

    def test_executes_query_preserving_types(self):
        cursor = self.create_cursor(preserve_types=True)

        cursor.execute('some statement')

        results = list(iter(cursor))
        self.assertEqual(results, [])
        cursor.session.post.assert_called_once_with(
            'http://localhost:8099/query/sql',
            json={'sql': "some statement OPTION(preserveType='true')"},
            headers=ANY)

    def test_executes_query_using_multistage_engine(self):
        cursor = self.create_cursor(use_multistage_engine=True)

        cursor.execute('some statement')

        results = list(iter(cursor))
        self.assertEqual(results, [])
        cursor.session.post.assert_called_once_with(
            'http://localhost:8099/query/sql', json={
                'sql': 'some statement',
                'queryOptions': 'useMultistageEngine=true'},
            headers=ANY)

    def test_executes_query_using_multistage_engine_plus_options(self):
        cursor = self.create_cursor(use_multistage_engine=True)

        cursor.execute('some statement', queryOptions='something')

        results = list(iter(cursor))
        self.assertEqual(results, [])
        cursor.session.post.assert_called_once_with(
            'http://localhost:8099/query/sql', json={
                'sql': 'some statement',
                'queryOptions': 'something;useMultistageEngine=true'},
            headers=ANY)

    def test_sends_correlation_id_header(self):
        cursor = self.create_cursor()

        cursor.execute('some statement')

        headers = cursor.session.post.call_args.kwargs['headers']
        self.assertIn('X-Correlation-Id', headers)
        # Validate the value is a valid UUID
        uuid.UUID(headers['X-Correlation-Id'])

    def test_sends_unique_correlation_id_per_request(self):
        cursor = self.create_cursor()

        cursor.execute('some statement')
        cursor.execute('some statement')

        calls = cursor.session.post.call_args_list
        id1 = calls[0].kwargs['headers']['X-Correlation-Id']
        id2 = calls[1].kwargs['headers']['X-Correlation-Id']
        self.assertNotEqual(id1, id2)

    def test_executes_query_with_complex_results(self):
        data = [
            ('age', 'INT', 12),
            ('name', 'STRING', 'John'),
            ('is_old', 'BOOLEAN', False),
            ('born_at', 'TIMESTAMP', '2010-01-01T00:30'),
            ('extras', 'JSON', '{"foo": "bar"}'),
            ('pet_peeve', 'UNKNOWN', 'bicycles'),
        ]
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': [d[0] for d in data],
                'columnDataTypes': [d[1] for d in data],
            },
            'rows': [
                [d[2] for d in data],
            ],
        })

        cursor.execute('some statement')

        results = list(iter(cursor))
        self.assertEqual(results, [
            [12, 'John', False, datetime.datetime(2010, 1, 1, 0, 30),
             {'foo': 'bar'}, '"bicycles"'],
        ])

    def test_executes_query_with_simple_results(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': ['age'],
                'columnDataTypes': ['INT'],
            },
            'rows': [
                [12],
            ],
        })

        cursor.execute('some statement')

        results = list(iter(cursor))
        self.assertEqual(results, [
            [12],
        ])

    def test_executes_query_with_none(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': ['age'],
                'columnDataTypes': ['UNKNOWN'],
            },
            'rows': [
                [None],
            ],
        })

        cursor.execute('some statement')

        results = list(iter(cursor))
        self.assertEqual(results, [
            [None],
        ])

    def test_executes_query_with_auth(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': ['age'],
                'columnDataTypes': ['INT'],
            },
            'rows': [
                [1],
            ],
        }, username='john.doe', password='mypass')

        cursor.execute('some statement')

        cursor.session.post.assert_called_once_with(
            'http://localhost:8099/query/sql',
            json={'sql': 'some statement'},
            headers=ANY,
            auth=(b'john.doe', b'mypass'),
        )

    def test_raises_database_error_if_problem_with_json(self):
        cursor = db.Cursor(
            host='localhost', session=MagicMock(spec=httpx.Client))
        cursor.session.is_closed = False
        response = cursor.session.post.return_value
        response.json.side_effect = ValueError()
        response.status_code = 200

        with self.assertRaises(exceptions.DatabaseError):
            cursor.execute('some statement')

    def test_raises_database_error_if_server_exception(self):
        cursor = self.create_cursor({}, extra_payload={
            'exceptions': ['something', 'wrong']
        })

        with self.assertRaises(exceptions.DatabaseError):
            cursor.execute('some statement')

    def test_raises_database_error_if_no_column_names(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': [],
                'columnDataTypes': [],
            },
            'rows': [],
        })

        with self.assertRaises(exceptions.DatabaseError):
            cursor.execute('some statement')

    def test_executes_query_with_results_and_debug_enabled(self):
        data = [
            ('age', 'INT', 12),
        ]
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': [d[0] for d in data],
                'columnDataTypes': [d[1] for d in data],
            },
            'rows': [
                [d[2] for d in data],
            ],
        }, debug=True)

        with patch.object(db, 'logger') as mock_logger:
            cursor.execute('some statement')

            self.assertGreater(len(mock_logger.info.mock_calls), 0)

    def test_raises_exception_if_error_in_status_code(self):
        cursor = self.create_cursor({}, status_code=400)

        with self.assertRaises(exceptions.ProgrammingError):
            cursor.execute('some statement')

    def test_cannot_execute_many(self):
        cursor = self.create_cursor({})

        with self.assertRaises(exceptions.NotSupportedError):
            cursor.executemany('some statement')

    def test_fetches_many_results(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': ['age'],
                'columnDataTypes': ['INT'],
            },
            'rows': [[1], [2], [3]],
        })

        cursor.execute('some statement')

        self.assertEqual(cursor.fetchmany(2), [[1], [2]])

    def test_fetches_all_results(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': ['age'],
                'columnDataTypes': ['INT'],
            },
            'rows': [[1], [2], [3]],
        })

        cursor.execute('some statement')

        self.assertEqual(cursor.fetchall(), [[1], [2], [3]])

    def test_fetches_with_schema(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': ['age'],
                'columnDataTypes': ['INT'],
            },
            'rows': [[1]],
        })

        cursor.execute('some statement')

        self.assertEqual(cursor.fetchwithschema(), {
            'results': [[1]],
            'schema': [{'name': 'age', 'type': 'INT'}]
        })

    def test_does_nothing_for_setinputsizes(self):
        cursor = self.create_cursor()

        cursor.setinputsizes(123)

        # All good, nothing happened

    def test_does_nothing_for_setoutputsizes(self):
        cursor = self.create_cursor()

        cursor.setoutputsizes(123)

        # All good, nothing happened

    def test_exposes_issue_66_stats(self):
        expected_stats = {
            'numServersQueried': 3,
            'numServersResponded': 3,
            'numSegmentsQueried': 15,
            'numSegmentsProcessed': 14,
            'numSegmentsMatched': 12,
            'numConsumingSegmentsQueried': 2,
            'numDocsScanned': 200,
            'numEntriesScannedInFilter': 40,
            'numEntriesScannedPostFilter': 25,
            'numGroupsLimitReached': False,
            'totalDocs': 10000,
            'timeUsedMs': 9,
            'minConsumingFreshnessTimeMs': 1730000000000,
            'numSegmentsPrunedByBroker': 4,
        }
        cursor = self.create_cursor(
            {
                'dataSchema': {
                    'columnNames': ['age'],
                    'columnDataTypes': ['INT'],
                },
                'rows': [[1]],
            },
            extra_payload=expected_stats,
        )

        cursor.execute('some statement')

        for key, value in expected_stats.items():
            self.assertEqual(cursor.query_stats.get(key), value)

    def test_exposes_query_stats(self):
        cursor = self.create_cursor(
            {
                'dataSchema': {
                    'columnNames': ['age'],
                    'columnDataTypes': ['INT'],
                },
                'rows': [[1]],
            },
            extra_payload={
                'timeUsedMs': 7,
                'numDocsScanned': 12,
                'numGroupsLimitReached': True,
            },
        )

        cursor.execute('some statement')

        self.assertEqual(cursor.query_stats, {
            'numServersResponded': 1,
            'numServersQueried': 1,
            'timeUsedMs': 7,
            'numDocsScanned': 12,
            'numGroupsLimitReached': True,
        })
        self.assertEqual(cursor.timeUsedMs, 7)

    def test_excludes_non_scalar_sections_from_query_stats(self):
        cursor = self.create_cursor(
            {
                'dataSchema': {
                    'columnNames': ['age'],
                    'columnDataTypes': ['INT'],
                },
                'rows': [[1]],
            },
            extra_payload={
                'timeUsedMs': 3,
                'traceInfo': {'broker': 'b1'},
                'exceptions': [],
            },
        )

        cursor.execute('some statement')

        self.assertEqual(cursor.query_stats, {
            'numServersResponded': 1,
            'numServersQueried': 1,
            'timeUsedMs': 3,
        })

    def test_checks_raw_query_response_with_single_stage_and_status_code_200(self):
        cursor = self.create_cursor(
                    {
                        'dataSchema': {
                            'columnNames': ['age'],
                            'columnDataTypes': ['INT'],
                        },
                        'rows': [[1], [2], [3]],
                    },
                    status_code=200,
                    extra_payload={'numGroupsLimitReached': True},
                    use_multistage_engine=False
                )
        cursor.execute('some statement')
        raw_query_response = {
            'response': {
                'numServersResponded': 1,
                'numServersQueried': 1,
                'resultTable': {
                    'dataSchema': {'columnNames': ['age'], 'columnDataTypes': ['INT']},
                    'rows': [[1], [2], [3]],
                },
                'numGroupsLimitReached': True,
            },
            'status_code': 200,
        }
        self.assertEqual(cursor.raw_query_response, raw_query_response)

    def test_checks_raw_query_response_with_multi_stage_and_status_code_200(self):
        cursor = self.create_cursor(
                    {
                        'dataSchema': {
                            'columnNames': ['age'],
                            'columnDataTypes': ['INT'],
                        },
                        'rows': [[1], [2], [3]],
                    },
                    status_code=200,
                    extra_payload={'numGroupsLimitReached': True},
                    use_multistage_engine=True
                )
        cursor.execute('some statement')
        raw_query_response = {
            'response': {
                'numServersResponded': 1,
                'numServersQueried': 1,
                'resultTable': {
                    'dataSchema': {'columnNames': ['age'], 'columnDataTypes': ['INT']},
                    'rows': [[1], [2], [3]],
                },
                'numGroupsLimitReached': True,
            },
            'status_code': 200,
        }
        self.assertEqual(cursor.raw_query_response, raw_query_response)

    def test_checks_raw_query_response_with_single_stage_and_status_code_400(self):
        cursor = self.create_cursor(
            {
                'dataSchema': {
                    'columnNames': ['age'],
                    'columnDataTypes': ['INT'],
                },
                'rows': [[1], [2], [3]],
            },
            status_code=400,
            extra_payload={'exceptions': ['something', 'wrong']},
            use_multistage_engine=False
        )
        with self.assertRaises(exceptions.ProgrammingError):
            cursor.execute('some statement')
        raw_query_response = {
            'response': {
                'numServersResponded': 1,
                'numServersQueried': 1,
                'resultTable': {
                    'dataSchema': {'columnNames': ['age'], 'columnDataTypes': ['INT']},
                    'rows': [[1], [2], [3]],
                },
                'exceptions': ['something', 'wrong'],
            },
            'status_code': 400,
        }
        self.assertEqual(cursor.raw_query_response, raw_query_response)

    def test_checks_raw_query_response_with_multi_stage_and_status_code_400(self):
        cursor = self.create_cursor(
            {
                'dataSchema': {
                    'columnNames': ['age'],
                    'columnDataTypes': ['INT'],
                },
                'rows': [[1], [2], [3]],
            },
            status_code=400,
            extra_payload={'exceptions': ['something', 'wrong']},
            use_multistage_engine=True
        )
        with self.assertRaises(exceptions.ProgrammingError):
            cursor.execute('some statement')
        raw_query_response = {
            'response': {
                'numServersResponded': 1,
                'numServersQueried': 1,
                'resultTable': {
                    'dataSchema': {'columnNames': ['age'], 'columnDataTypes': ['INT']},
                    'rows': [[1], [2], [3]],
                },
                'exceptions': ['something', 'wrong'],
            },
            'status_code': 400,
        }
        self.assertEqual(cursor.raw_query_response, raw_query_response)


class AsyncCursorTest(IsolatedAsyncioTestCase):
    def create_cursor(
            self, result_table: Optional[Dict[str, Any]] = None,
            status_code: int = 200, debug: bool = False,
            extra_payload: Optional[Dict[str, Any]] = None,
            username: Optional[str] = None,
            password: Optional[str] = None,
            preserve_types: bool = False,
    ) -> db.AsyncCursor:
        cursor = db.AsyncCursor(
            host='localhost', session=AsyncMock(spec=httpx.AsyncClient),
            debug=debug, username=username, password=password,
            preserve_types=preserve_types,
        )
        cursor.session.is_closed = False
        payload = {
            'numServersResponded': 1,
            'numServersQueried': 1,
        }
        if result_table is not None:
            payload['resultTable'] = result_table
        if extra_payload:
            payload.update(extra_payload)
        response = httpx.Response(200, json=payload)
        cursor.session.post.return_value = response
        return cursor

    async def test_executes_query_with_auth(self):
        cursor = self.create_cursor({
            'dataSchema': {
                'columnNames': ['age'],
                'columnDataTypes': ['INT'],
            },
            'rows': [
                [1],
            ],
        }, username='john.doe', password='mypass')

        await cursor.execute('some statement')

        cursor.session.post.assert_called_once_with(
            'http://localhost:8099/query/sql',
            json={'sql': 'some statement'},
            headers=ANY,
            auth=(b'john.doe', b'mypass'),
        )

    async def test_sends_correlation_id_header(self):
        cursor = self.create_cursor()

        await cursor.execute('some statement')

        headers = cursor.session.post.call_args.kwargs['headers']
        self.assertIn('X-Correlation-Id', headers)
        # Validate the value is a valid UUID
        uuid.UUID(headers['X-Correlation-Id'])

    async def test_sends_unique_correlation_id_per_request(self):
        cursor = self.create_cursor()

        await cursor.execute('some statement')
        await cursor.execute('some statement')

        calls = cursor.session.post.call_args_list
        id1 = calls[0].kwargs['headers']['X-Correlation-Id']
        id2 = calls[1].kwargs['headers']['X-Correlation-Id']
        self.assertNotEqual(id1, id2)

    async def test_exposes_query_stats(self):
        cursor = self.create_cursor(
            {
                'dataSchema': {
                    'columnNames': ['age'],
                    'columnDataTypes': ['INT'],
                },
                'rows': [[1]],
            },
            extra_payload={
                'timeUsedMs': 5,
                'numEntriesScannedPostFilter': 18,
            },
        )

        await cursor.execute('some statement')

        self.assertEqual(cursor.query_stats, {
            'numServersResponded': 1,
            'numServersQueried': 1,
            'timeUsedMs': 5,
            'numEntriesScannedPostFilter': 18,
        })
        self.assertEqual(cursor.timeUsedMs, 5)


class EscapeTest(TestCase):
    def test_escapes_asterisk(self):
        self.assertEqual(db.escape_parameter('*'), '*')

    def test_escapes_string(self):
        self.assertEqual(db.escape_parameter("what 'foo' means"), "'what ''foo'' means'")

    def test_escapes_int(self):
        self.assertEqual(db.escape_parameter(1), 1)

    def test_escapes_float(self):
        self.assertEqual(db.escape_parameter(1.0), 1.0)

    def test_escapes_bool(self):
        self.assertEqual(db.escape_parameter(True), 'TRUE')
        self.assertEqual(db.escape_parameter(False), 'FALSE')

    def test_escapes_list(self):
        self.assertEqual(db.escape_parameter([1, 'two']), "1, 'two'")

    def test_bypasses_escaping_unknown_types(self):
        self.assertEqual(db.escape_parameter({1, 2}), {1, 2})

    def test_escapes_percent(self):
        self.assertEqual(db.escape_operation("some query with %"), "some query with %%")
        self.assertEqual(db.escape_operation("some query with %(var)s"), "some query with %(var)s")
