"""
WARNING: If you're using an IDE that tinkers with the PYTHONPATH this test
module might not run at all inside of it, like in PyCharm.

This is probably related to the name we have for module "pinotdb.sqlalchemy",
which might be confusing PyCharm between that module and "sqlalchemy" (the main
module for the SQLAlchemy library).

So it's better to stick to running unit tests from the CLI instead, at least
for now.
"""

import asyncio
import collections
from unittest import TestCase
from unittest.mock import patch
import json

import responses
from sqlalchemy import (
    BigInteger, Column, Integer, MetaData, String, Table,
    column, func, select, text, types,
)
from sqlalchemy.dialects import registry
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

import pinotdb
from pinotdb import exceptions, sqlalchemy as ps


class PinotTestCase(TestCase):
    def setUp(self) -> None:
        self.dialect = ps.PinotDialect(server='http://localhost:9000')


class _FakeAsyncPinotCursor:
    def __init__(self):
        self.description = [("col1", None, None, None, None, None, None)]
        self.rowcount = 1
        self.arraysize = 1
        self.closed = False
        self._rows = collections.deque([[1]])

    async def execute(self, operation, parameters=None):
        return self

    def fetchone(self):
        if self._rows:
            return self._rows.popleft()
        return None

    def fetchmany(self, size=None):
        size = size or self.arraysize
        return [self._rows.popleft() for _ in range(min(size, len(self._rows)))]

    def fetchall(self):
        rows = list(self._rows)
        self._rows.clear()
        return rows

    async def close(self):
        self.closed = True

    def __iter__(self):
        return iter(self._rows)


class _FakeAsyncPinotConnection:
    def __init__(self):
        self.closed = False
        self._cursors = []

    def cursor(self):
        cursor = _FakeAsyncPinotCursor()
        self._cursors.append(cursor)
        return cursor

    async def close(self):
        self.closed = True
        for cursor in self._cursors:
            if not cursor.closed:
                await cursor.close()


class PinotAsyncDialectTest(PinotTestCase):
    def test_marks_dialect_as_async(self):
        self.assertTrue(ps.PinotAsyncDialect.is_async)
        self.assertEqual(ps.PinotAsyncDialect.driver, "rest_async")

    @patch("pinotdb.sqlalchemy.pinotdb.connect_async")
    def test_works_with_create_async_engine(self, connect_async):
        registry.register("pinot.async", "pinotdb.sqlalchemy", "PinotAsyncDialect")

        fake_connections = []

        def _connect_async(*args, **kwargs):
            connection = _FakeAsyncPinotConnection()
            fake_connections.append((args, kwargs, connection))
            return connection

        connect_async.side_effect = _connect_async

        engine = create_async_engine(
            "pinot+async://localhost:8000/query/sql"
            "?controller=http://localhost:9000/"
        )

        async def _run_query():
            async with engine.connect() as connection:
                result = await connection.execute(text("SELECT 1"))
                self.assertEqual(result.scalar_one(), 1)
            await engine.dispose()

        asyncio.run(_run_query())

        self.assertGreaterEqual(connect_async.call_count, 1)
        kwargs = fake_connections[0][1]
        self.assertEqual(kwargs["host"], "localhost")
        self.assertEqual(kwargs["port"], 8000)
        self.assertEqual(kwargs["path"], "query/sql")
        self.assertEqual(kwargs["scheme"], "http")


class PinotDialectTest(PinotTestCase):
    def test_gets_pinot_db_module_as_dbapi(self):
        """
        The dialect exports the symbols necessary to implement the DBAPI 2
        protocol, so this is what's being tested here.
        """

        api = ps.PinotDialect.dbapi()

        self.assertIs(api, pinotdb)

    def test_creates_connection_args(self):
        url = make_url(
            'pinot://localhost:8000/query/sql?controller='
            'http://localhost:9000/')

        cargs, cparams = self.dialect.create_connect_args(url)

        self.assertEqual(cargs, [])
        self.assertEqual(cparams, {
            'debug': False,
            'scheme': 'http',
            'host': 'localhost',
            'port': 8000,
            'path': 'query/sql',
            'username': None,
            'password': None,
            'verify_ssl': True,
            'timeout': 10.0,
        })

    def test_checks_timeout_in_query_params(self):
        url = make_url(
            'pinot://localhost:8000/query/sql?controller='
            'http://localhost:9000/&&verify_ssl=True&&timeout=100')

        cargs, cparams = self.dialect.create_connect_args(url)

        self.assertEqual(cargs, [])
        self.assertEqual(cparams, {
            'debug': False,
            'scheme': 'http',
            'host': 'localhost',
            'port': 8000,
            'path': 'query/sql',
            'username': None,
            'password': None,
            'verify_ssl': True,
            'timeout': 100,
        })

    def test_creates_connection_args_without_query(self):
        url = make_url('pinot://localhost:8000/query/sql')

        cargs, cparams = self.dialect.create_connect_args(url)

        self.assertEqual(cargs, [])
        self.assertEqual(cparams, {
            'debug': False,
            'scheme': 'http',
            'host': 'localhost',
            'port': 8000,
            'path': 'query/sql',
            'username': None,
            'password': None,
            'verify_ssl': True,
            'timeout': 10.0,
        })

    def test_can_instantiate_with_server(self):
        dialect = ps.PinotDialect(server='http://localhost:9000/')

        self.assertEqual(dialect._controller, 'http://localhost:9000/')

    def test_gets_insecure_broker_port_by_default(self):
        self.assertEqual(self.dialect.get_default_broker_port(), 8000)

    def test_gets_secure_broker_port_from_https_dialect(self):
        self.assertEqual(ps.PinotHTTPSDialect().get_default_broker_port(), 443)

    @responses.activate
    def test_gets_metadata_from_controller(self):
        url = f'{self.dialect._controller}/some-path'
        responses.get(url, json={'foo': 'bar'})

        metadata = self.dialect.get_metadata_from_controller('some-path')

        self.assertEqual(metadata, {'foo': 'bar'})

    @responses.activate
    def test_cannot_get_metadata_if_broken_json(self):
        url = f'{self.dialect._controller}/some-path'
        responses.get(url, body='something')

        with self.assertRaises(exceptions.DatabaseError):
            self.dialect.get_metadata_from_controller('some-path')

    def test_gets_schema_names(self):
        names = self.dialect.get_schema_names('some connection')
        self.assertEqual(names, ['default'])
        self.dialect._database = 'foo'
        names = self.dialect.get_schema_names('some connection')
        self.assertEqual(names, ['foo'])

    @responses.activate
    def test_gets_table_names_from_controller(self):
        url = f'{self.dialect._controller}/tables'
        responses.get(url, json={'tables': ['foo', 'bar']})

        names = self.dialect.get_table_names('some connection')

        self.assertEqual(names, ['foo', 'bar'])

    @responses.activate
    def test_checks_that_table_exists(self):
        url = f'{self.dialect._controller}/tables'
        responses.get(url, json={'tables': ['foo', 'bar']})

        self.assertTrue(self.dialect.has_table('some connection', 'foo'))
        self.assertFalse(self.dialect.has_table('some connection', 'none'))

    def test_gets_empty_views(self):
        self.assertEqual(self.dialect.get_view_names('conn'), [])

    def test_gets_empty_table_options(self):
        self.assertEqual(self.dialect.get_table_options('conn', 'table'), {})

    @responses.activate
    def test_gets_columns_from_server(self):
        table_name = 'some-table'
        url = f'{self.dialect._controller}/tables/{table_name}/schema'
        responses.get(url, json={
            'tables': [table_name],
            'timeFieldSpec': {},
            'dimensionFieldSpecs': [{'name': 'foo', 'dataType': 'STRING'}],
            'metricFieldSpecs': [{'name': 'bar', 'dataType': 'STRING'}],
            'dateTimeFieldSpecs': [{'name': 'baz', 'dataType': 'STRING'}],
        })

        columns = self.dialect.get_columns('conn', table_name)

        self.assertEqual(columns, [
            {
                'default': None,
                'name': 'foo',
                'nullable': True,
                'type': String,
            },
            {
                'default': None,
                'name': 'bar',
                'nullable': True,
                'type': String,
            },
            {
                'default': None,
                'name': 'baz',
                'nullable': True,
                'type': String,
            },
        ])

    @responses.activate
    def test_gets_columns_with_different_default_values(self):
        table_name = 'some-table'
        url = f'{self.dialect._controller}/tables/{table_name}/schema'
        responses.get(url, json={
            'tables': [table_name],
            'timeFieldSpec': {},
            'dimensionFieldSpecs': [{
                'name': 'foo',
                'dataType': 'INT',
                'defaultNullValue': 123,
            }],
        })

        columns = self.dialect.get_columns('conn', table_name)

        self.assertEqual(columns, [
            {
                'default': '123',
                'name': 'foo',
                'nullable': True,
                'type': BigInteger,
            },
        ])

    @responses.activate
    def test_gets_columns_with_big_decimal_type(self):
        table_name = 'some-table'
        url = f'{self.dialect._controller}/tables/{table_name}/schema'
        responses.get(url, json={
            'tables': [table_name],
            'timeFieldSpec': {},
            'dimensionFieldSpecs': [{
                'name': 'price',
                'dataType': 'BIG_DECIMAL',
                'defaultNullValue': '0.00',
            }],
        })

        columns = self.dialect.get_columns('conn', table_name)

        self.assertEqual(columns, [
            {
                'default': '0.00',
                'name': 'price',
                'nullable': True,
                'type': types.Numeric,
            },
        ])

    @responses.activate
    def test_gets_columns_with_time_spec(self):
        table_name = 'some-table'
        url = f'{self.dialect._controller}/tables/{table_name}/schema'
        responses.get(url, json={
            'tables': [table_name],
            'timeFieldSpec': {
                'incomingGranularitySpec': {
                    'name': 'time', 'dataType': 'STRING'}
            },
            'dateTimeFieldSpecs': [],
        })

        columns = self.dialect.get_columns('conn', table_name)

        self.assertEqual(columns, [
            {
                'default': None,
                'name': 'time',
                'nullable': True,
                'type': String,
            },
        ])

    def test_gets_pk_constraint(self):
        result = self.dialect.get_pk_constraint('conn', 'some-table')

        self.assertEqual(result, {"constrained_columns": [], "name": None})

    def test_gets_table_comment(self):
        result = self.dialect.get_table_comment('conn', 'some-table')

        self.assertEqual(result, {"text": ""})

    def test_gets_foreign_keys(self):
        result = self.dialect.get_foreign_keys('conn', 'some-table')

        self.assertEqual(result, [])

    def test_gets_check_constraints(self):
        result = self.dialect.get_check_constraints('conn', 'some-table')

        self.assertEqual(result, [])

    def test_gets_indexes(self):
        result = self.dialect.get_indexes('conn', 'some-table')

        self.assertEqual(result, [])

    def test_gets_unique_constraints(self):
        result = self.dialect.get_unique_constraints('conn', 'some-table')

        self.assertEqual(result, [])

    def test_checks_unicode_returns(self):
        self.assertTrue(self.dialect._check_unicode_returns('conn'))

    def test_checks_unicode_description(self):
        self.assertTrue(self.dialect._check_unicode_description('conn'))

    def test_json_deserializer(self):
        # Test with string input
        self.assertEqual(self.dialect._json_deserializer('{"key": "value"}'), {"key": "value"})
        # Test with bytes input
        self.assertEqual(self.dialect._json_deserializer(b'{"key": "value"}'), {"key": "value"})
        # Test with already parsed JSON
        self.assertEqual(self.dialect._json_deserializer({"key": "value"}), {"key": "value"})
        # Test with non-JSON string - should raise JSONDecodeError
        with self.assertRaises(json.JSONDecodeError):
            self.dialect._json_deserializer("not json")

    def test_get_view_definition(self):
        self.assertIsNone(self.dialect.get_view_definition('conn', 'view_name'))

    def test_do_rollback(self):
        self.assertIsNone(self.dialect.do_rollback('conn'))


class PinotMultiStageDialectTest(PinotTestCase):
    def setUp(self) -> None:
        self.dialect = ps.PinotMultiStageDialect(
            server='http://localhost:9000')

    def test_creates_connection_args(self):
        url = make_url(
            'pinot://localhost:8000/query/sql?controller='
            'http://localhost:9000/')

        cargs, cparams = self.dialect.create_connect_args(url)

        self.assertEqual(cargs, [])
        self.assertEqual(cparams, {
            'debug': False,
            'scheme': 'http',
            'host': 'localhost',
            'port': 8000,
            'path': 'query/sql',
            'username': None,
            'password': None,
            'verify_ssl': True,
            'timeout': 10.0,
            'use_multistage_engine': True,
        })


class PinotCompilerTest(PinotTestCase):
    def test_can_do_simple_select(self):
        metadata = MetaData()
        table = Table(
            'some_table', metadata,
            Column('some_column', Integer)
        )
        statement = select(column('some_column')).select_from(table)

        compiler = self.dialect.statement_compiler(self.dialect, statement)

        self.assertEqual(
            str(compiler),
            'SELECT some_column \nFROM some_table',
        )

    def test_can_do_select_with_reserved_words(self):
        metadata = MetaData()
        table = Table(
            'some_table', metadata,
            Column('order', Integer)
        )
        statement = select(column('order')).select_from(table)

        compiler = self.dialect.statement_compiler(self.dialect, statement)

        self.assertEqual(
            str(compiler),
            'SELECT "order" \nFROM some_table',
        )

    def test_can_do_select_with_labels(self):
        metadata = MetaData()
        table = Table(
            'some_table', metadata,
            Column('order', Integer)
        )
        statement = select(column('order').label('ord')).select_from(table)

        compiler = self.dialect.statement_compiler(self.dialect, statement)

        self.assertEqual(
            str(compiler),
            'SELECT "order" AS ord \nFROM some_table',
        )

    def test_can_select_table_directly(self):
        metadata = MetaData()
        table = Table(
            'some_table', metadata,
            Column('some_column', Integer)
        )
        statement = select(table.c.some_column)

        compiler = self.dialect.statement_compiler(self.dialect, statement)

        self.assertEqual(
            str(compiler),
            'SELECT some_table.some_column \nFROM some_table',
        )

    def test_count_without_args_compiles_to_count_star(self):
        metadata = MetaData()
        table = Table(
            'some_table', metadata,
            Column('some_column', Integer)
        )
        statement = select(func.count()).select_from(table)

        compiler = self.dialect.statement_compiler(self.dialect, statement)

        self.assertIn('count(*)', str(compiler))


class PinotTypeCompilerTest(PinotTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.compiler: ps.PinotTypeCompiler = self.dialect.type_compiler

    def test_compiles_real(self):
        self.assertEqual(self.compiler.visit_REAL(None), 'DOUBLE')

    def test_compiles_numeric(self):
        self.assertEqual(self.compiler.visit_NUMERIC(None), 'NUMERIC')

    def test_compiles_decimal(self):
        self.assertEqual(self.compiler.visit_DECIMAL(None), 'NUMERIC')

    def test_compiles_integer(self):
        self.assertEqual(self.compiler.visit_INTEGER(None), 'NUMERIC')

    def test_compiles_smallint(self):
        self.assertEqual(self.compiler.visit_SMALLINT(None), 'NUMERIC')

    def test_compiles_bigint(self):
        self.assertEqual(self.compiler.visit_BIGINT(None), 'NUMERIC')

    # TODO: Check if this is correct (seems strange to have boolean as long).
    def test_compiles_boolean(self):
        self.assertEqual(self.compiler.visit_BOOLEAN(None), 'NUMERIC')

    def test_compiles_timestamp(self):
        self.assertEqual(self.compiler.visit_TIMESTAMP(None), 'TIMESTAMP')

    def test_compiles_date(self):
        self.assertEqual(self.compiler.visit_DATE(None), 'NUMERIC')

    def test_compiles_char(self):
        self.assertEqual(self.compiler.visit_CHAR(None), 'VARCHAR')

    def test_compiles_nchar(self):
        self.assertEqual(self.compiler.visit_NCHAR(None), 'VARCHAR')

    def test_compiles_varchar(self):
        self.assertEqual(self.compiler.visit_VARCHAR(None), 'VARCHAR')

    def test_compiles_nvarchar(self):
        self.assertEqual(self.compiler.visit_NVARCHAR(None), 'VARCHAR')

    def test_compiles_text(self):
        self.assertEqual(self.compiler.visit_TEXT(None), 'VARCHAR')

    def test_compiles_binary(self):
        self.assertEqual(self.compiler.visit_BINARY(None), 'BYTES')

    def test_compiles_varbinary(self):
        self.assertEqual(self.compiler.visit_VARBINARY(None), 'BYTES')

    def test_compiles_datetime(self):
        self.assertEqual(self.compiler.visit_DATETIME(None), 'TIMESTAMP')

    def test_cannot_compile_time(self):
        with self.assertRaises(exceptions.NotSupportedError):
            self.compiler.visit_TIME(None)

    def test_cannot_compile_blob(self):
        with self.assertRaises(exceptions.NotSupportedError):
            self.compiler.visit_BLOB(None)

    def test_cannot_compile_clob(self):
        with self.assertRaises(exceptions.NotSupportedError):
            self.compiler.visit_CLOB(None)

    def test_cannot_compile_nclob(self):
        with self.assertRaises(exceptions.NotSupportedError):
            self.compiler.visit_NCLOB(None)
