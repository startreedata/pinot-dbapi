import collections
import sys
from urllib import parse

import requests
from requests.auth import HTTPBasicAuth
from sqlalchemy.engine import default
from sqlalchemy.engine.interfaces import AdaptedConnection
from sqlalchemy.sql import compiler
from sqlalchemy import pool, types
from sqlalchemy.util.concurrency import await_only

import pinotdb
from pinotdb import exceptions
from pinotdb import keywords
import logging

import json

logger = logging.getLogger(__name__)


class PinotCompiler(compiler.SQLCompiler):
    def visit_select(self, select, **kwargs):
        return super().visit_select(select, **kwargs)

    def visit_column(self, column, result_map=None, **kwargs):
        result_map = result_map or kwargs.pop("add_to_result_map", None)
        # This is a hack to modify the original column, but how do I clone it ?
        column.is_literal = True
        return super().visit_column(column, result_map, **kwargs)

    def visit_function(self, func, **kw):
        if func.name and func.name.lower() == "count":
            # Detect no-argument COUNT() and render it as COUNT(*) for Pinot.
            clauses = getattr(func, "clauses", None)
            if clauses is not None and len(clauses) == 0:
                # Pinot requires COUNT(*) instead of COUNT() with no args.
                return "count(*)"
        return super().visit_function(func, **kw)

    def escape_literal_column(self, text):
        # This is a hack to quote column names that conflict with reserved
        # words since 'column.is_literal = True'
        if text in self.preparer.reserved_words:
            return self.preparer.quote(super().escape_literal_column(text))
        return super().escape_literal_column(text)

    def visit_label(
        self,
        label,
        add_to_result_map=None,
        within_label_clause=False,
        within_columns_clause=False,
        render_label_as_label=None,
        **kw,
    ):
        return super().visit_label(
            label,
            add_to_result_map,
            within_label_clause,
            within_columns_clause,
            # Note: We force not to render labels in non-select clauses
            render_label_as_label=None,
            **kw,
        )


class PinotTypeCompiler(compiler.GenericTypeCompiler):
    def visit_REAL(self, type_, **kwargs):
        return "DOUBLE"

    def visit_NUMERIC(self, type_, **kwargs):
        return "NUMERIC"

    visit_DECIMAL = visit_NUMERIC
    visit_INTEGER = visit_NUMERIC
    visit_SMALLINT = visit_NUMERIC
    visit_BIGINT = visit_NUMERIC
    visit_BOOLEAN = visit_NUMERIC
    visit_TIMESTAMP = visit_NUMERIC
    visit_DATE = visit_NUMERIC

    def visit_CHAR(self, type_, **kwargs):
        return "VARCHAR"

    visit_NCHAR = visit_CHAR
    visit_VARCHAR = visit_CHAR
    visit_NVARCHAR = visit_CHAR
    visit_TEXT = visit_CHAR

    def visit_BINARY(self, type_, **kwargs):
        return "BYTES"

    visit_VARBINARY = visit_BINARY

    def visit_DATETIME(self, type_, **kwargs):
        return "TIMESTAMP"

    def visit_TIME(self, type_, **kwargs):
        raise exceptions.NotSupportedError("Type TIME is not supported")

    def visit_BLOB(self, type_, **kwargs):
        raise exceptions.NotSupportedError("Type BLOB is not supported")

    def visit_CLOB(self, type_, **kwargs):
        raise exceptions.NotSupportedError("Type CBLOB is not supported")

    def visit_NCLOB(self, type_, **kwargs):
        raise exceptions.NotSupportedError("Type NCBLOB is not supported")


class PinotIdentifierPareparer(compiler.IdentifierPreparer):
    reserved_words = set(
        [e.lower()
         for e in (keywords.CALCITE_KEYWORDS ^ keywords.SUPERSET_KEYWORDS)]
    )

    def __init__(
        self,
        dialect,
        initial_quote='"',
        final_quote=None,
        escape_quote='"',
        omit_schema=True,
    ):
        # SQLAlchemy 2.x changed the IdentifierPreparer __init__ signature.
        # Use keyword args so omit_schema is applied correctly (we don't
        # support schemas in Pinot and avoid emitted SQL like
        # `"default"."table"`.
        super(PinotIdentifierPareparer, self).__init__(
            dialect,
            initial_quote=initial_quote,
            final_quote=final_quote,
            escape_quote=escape_quote,
            omit_schema=omit_schema,
        )


def extract_table_name(fqn):
    split = fqn.split(".", 2)
    return fqn if len(split) == 1 else split[1]



class PinotAsyncAdaptDBAPIModule:
    def __init__(self, dbapi_module):
        self._dbapi_module = dbapi_module
        self.paramstyle = dbapi_module.paramstyle
        self.apilevel = dbapi_module.apilevel
        self.threadsafety = dbapi_module.threadsafety
        self.Warning = dbapi_module.Warning
        self.Error = dbapi_module.Error
        self.InterfaceError = dbapi_module.InterfaceError
        self.DatabaseError = dbapi_module.DatabaseError
        self.InternalError = dbapi_module.InternalError
        self.OperationalError = dbapi_module.OperationalError
        self.ProgrammingError = dbapi_module.ProgrammingError
        self.IntegrityError = dbapi_module.IntegrityError
        self.DataError = dbapi_module.DataError
        self.NotSupportedError = dbapi_module.NotSupportedError

    def connect(self, *args, **kwargs):
        return PinotAsyncAdaptConnection(
            self,
            self._dbapi_module.connect_async(*args, **kwargs),
        )


class PinotAsyncAdaptConnection(AdaptedConnection):
    __slots__ = ("dbapi", "_connection")

    def __init__(self, dbapi, connection):
        self.dbapi = dbapi
        self._connection = connection

    def cursor(self, server_side=False):
        return PinotAsyncAdaptCursor(self)

    def execute(self, operation, parameters=None):
        cursor = self.cursor()
        cursor.execute(operation, parameters)
        return cursor

    def rollback(self):
        # Pinot has no transaction support.
        return None

    def commit(self):
        # Pinot has no transaction support.
        return None

    def close(self):
        try:
            await_only(self._connection.close())
        except Exception as error:
            self._handle_exception(error)

    def _handle_exception(self, error):
        exc_info = sys.exc_info()
        raise error.with_traceback(exc_info[2])


class PinotAsyncAdaptCursor:
    __slots__ = (
        "_adapt_connection",
        "_cursor",
        "_rows",
        "_description",
        "_rowcount",
        "_arraysize",
    )

    def __init__(self, adapt_connection):
        self._adapt_connection = adapt_connection
        self._cursor = adapt_connection._connection.cursor()
        self._rows = collections.deque()
        self._description = None
        self._rowcount = -1
        self._arraysize = self._cursor.arraysize

    @property
    def description(self):
        if self._cursor is None:
            return self._description
        return self._cursor.description

    @property
    def rowcount(self):
        if self._cursor is None:
            return self._rowcount
        return self._cursor.rowcount

    @property
    def arraysize(self):
        if self._cursor is None:
            return self._arraysize
        return self._cursor.arraysize

    @arraysize.setter
    def arraysize(self, value):
        self._arraysize = value
        if self._cursor is not None:
            self._cursor.arraysize = value

    def close(self):
        self._rows.clear()
        if self._cursor is None:
            return

        try:
            await_only(self._cursor.close())
            self._cursor = None
        except Exception as error:
            self._adapt_connection._handle_exception(error)

    def execute(self, operation, parameters=None):
        try:
            if parameters is None:
                await_only(self._cursor.execute(operation))
            else:
                await_only(self._cursor.execute(operation, parameters))

            self._description = self._cursor.description
            self._rowcount = self._cursor.rowcount
            if self._description:
                self._rows = collections.deque(self._cursor.fetchall())
            else:
                self._rows.clear()
            return self
        except Exception as error:
            self._adapt_connection._handle_exception(error)

    def executemany(self, operation, seq_of_parameters=None):
        return self._cursor.executemany(operation, seq_of_parameters)

    def fetchone(self):
        if self._rows:
            return self._rows.popleft()
        return None

    def fetchmany(self, size=None):
        if size is None:
            size = self.arraysize
        return [
            self._rows.popleft() for _ in range(min(size, len(self._rows)))
        ]

    def fetchall(self):
        rows = list(self._rows)
        self._rows.clear()
        return rows

    def __iter__(self):
        while self._rows:
            yield self._rows.popleft()

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        self.close()

    async def _async_soft_close(self):
        if self._cursor is None:
            return

        self._description = self._cursor.description
        await self._cursor.close()
        self._cursor = None


_PINOT_ASYNC_DBAPI = PinotAsyncAdaptDBAPIModule(pinotdb)


class PinotDialect(default.DefaultDialect):

    name = "pinot"
    scheme = "http"
    driver = "rest"
    engine_type = "v1"
    preparer = PinotIdentifierPareparer
    statement_compiler = PinotCompiler
    type_compiler = PinotTypeCompiler
    supports_schemas = False
    supports_statement_cache = False
    supports_alter = False
    supports_pk_autoincrement = False
    supports_default_values = False
    supports_empty_insert = False
    supports_unicode_statements = True
    supports_unicode_binds = True
    returns_unicode_strings = True
    description_encoding = None
    supports_native_boolean = True
    supports_simple_order_by_label = False
    broker_http_port = 8000
    broker_https_port = 443

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._controller = None
        self._username = None
        self._password = None
        self._debug = False
        self._verify_ssl = True
        self._timeout = 10.0
        self._database = None
        self.update_from_kwargs(kwargs)

    def update_from_kwargs(self, givenkw):
        kwargs = givenkw.copy() if givenkw else {}
        # For backward compatible
        if "server" in kwargs:
            self._controller = kwargs.pop("server")
        if "controller" in kwargs:
            self._controller = kwargs.pop("controller")
        if "username" in kwargs:
            kwargs["username"] = self._username = kwargs.pop("username")
        if "password" in kwargs:
            kwargs["password"] = self._password = kwargs.pop("password")
        if "database" in kwargs:
            kwargs["database"] = self._database = kwargs.pop("database")
        kwargs["debug"] = self._debug = bool(kwargs.get("debug", False))
        kwargs["verify_ssl"] = self._verify_ssl = (
            str(kwargs.get("verify_ssl", "true")).lower() in ['true']
        )
        kwargs["timeout"] = self._timeout = (
            float(kwargs.get('timeout'))
            if kwargs.get('timeout')
            else None
        )
        logger.info(
            "Updated pinot dialect options: debug=%s, verify_ssl=%s, timeout=%s, database_set=%s",
            self._debug,
            self._verify_ssl,
            self._timeout,
            self._database is not None,
        )
        return kwargs

    @classmethod
    def dbapi(cls):
        return pinotdb

    @classmethod
    def import_dbapi(cls):
        # SQLAlchemy 2.x renamed dbapi() -> import_dbapi(). Keep dbapi() above
        # for external callers; SQLAlchemy itself will use import_dbapi().
        return pinotdb

    def get_default_broker_port(self):
        if self.scheme.lower() == "https":
            return self.broker_https_port
        return self.broker_http_port

    def create_connect_args(self, url):
        kwargs = {
            "host": url.host,
            "port": url.port or self.get_default_broker_port(),
            "path": url.database,
            "scheme": self.scheme,
            "username": url.username,
            "password": url.password,
            "verify_ssl": self._verify_ssl or True,
            "timeout": float(self._timeout) if self._timeout else 10.0,
        }
        if self.engine_type == "multi_stage":
            kwargs.update({"use_multistage_engine": True})
        if url.query:
            kwargs.update(url.query)

        kwargs = self.update_from_kwargs(kwargs)
        return ([], kwargs)

    def get_metadata_from_controller(self, path):
        url = parse.urljoin(self._controller, path)
        headers = {"Accept": "application/json"}
        # Only send Database header when explicitly set to a non-None value,
        # always as a string; Requests rejects non-string header values.
        if self._database is not None:
            headers["Database"] = str(self._database)

        # Only send basic auth when credentials are provided; passing None here
        # triggers deprecation warnings in Requests.
        auth = (
            HTTPBasicAuth(self._username, self._password)
            if self._username and self._password
            else None
        )

        r = requests.get(
            url,
            headers=headers,
            verify=self._verify_ssl,
            auth=auth,
        )
        try:
            result = r.json()
        except ValueError as e:
            raise exceptions.DatabaseError(
                "Got invalid json response from "
                f"{self._controller}:{path}: {r.text}"
            ) from e
        # Skipping coverage of log lines - because covering them adds no value.
        if self._debug:  # pragma: no cover
            logger.info(
                "metadata get on %s:%s returned %s",
                self._controller,
                path,
                result,
            )
        return result

    def get_schema_names(self, connection, **kwargs):
        if self._database:
            return [self._database]
        else:
            return ['default']

    def has_table(self, connection, table_name, schema=None):
        return table_name in self.get_table_names(connection, schema)

    def get_table_names(self, connection, schema=None, **kwargs):
        resp = self.get_metadata_from_controller("/tables")
        if 'tables' in resp:
            return list(map(extract_table_name, resp["tables"]))
        else:
            return []

    def get_view_names(self, connection, schema=None, **kwargs):
        return []

    def get_table_options(self, connection, table_name, schema=None, **kwargs):
        return {}

    def get_columns(self, connection, table_name, schema=None, **kwargs):
        payload = self.get_metadata_from_controller(
            f"/tables/{table_name}/schema"
        )

        logger.info(
            "Getting columns for %s from %s: %s",
            table_name,
            self._controller,
            payload,
        )
        specs = (
            payload.get("dimensionFieldSpecs", [])
            + payload.get("metricFieldSpecs", [])
            + payload.get("dateTimeFieldSpecs", [])
        )

        timeFieldSpec = payload.get("timeFieldSpec")
        if timeFieldSpec:
            specs.append(
                timeFieldSpec.get(
                    "outgoingGranularitySpec",
                    timeFieldSpec["incomingGranularitySpec"],
                )
            )

        columns = [
            {
                "name": spec["name"],
                "type": get_type(spec["dataType"], spec.get("fieldSize")),
                "nullable": True,
                "default": get_default(spec.get("defaultNullValue", "null")),
            }
            for spec in specs
        ]

        return columns

    def get_pk_constraint(self, connection, table_name, schema=None, **kwargs):
        return {"constrained_columns": [], "name": None}

    def get_foreign_keys(self, connection, table_name, schema=None, **kwargs):
        return []

    def get_check_constraints(
        self, connection, table_name, schema=None, **kwargs
    ):
        return []

    def get_table_comment(self, connection, table_name, schema=None, **kwargs):
        return {"text": ""}

    def get_indexes(self, connection, table_name, schema=None, **kwargs):
        return []

    def get_unique_constraints(
        self, connection, table_name, schema=None, **kwargs
    ):
        return []

    def get_view_definition(
        self, connection, view_name, schema=None, **kwargs
    ):
        pass

    def do_rollback(self, dbapi_connection):
        pass

    def _check_unicode_returns(self, connection, additional_tests=None):
        return True

    def _check_unicode_description(self, connection):
        return True

    # Fix for SQL Alchemy error
    def _json_deserializer(self, content: any):
        """
        This function fixes the following error from SQLAlchemy:

        Traceback (most recent call last):
        File "...sqlalchemy/sql/sqltypes.py", line 2714, in result_processor
        json_deserializer = dialect._json_deserializer or json.loads
        AttributeError: 'PinotDialect' object has no attribute
        '_json_deserializer'

        The expected behavior is to simply return the passed object (called
        `content`) because the json.loads() method should already have been
        called in `db.py`. However, if the content is still one of the
        supported types for json.loads to deserialize, it will try to do so.
        """
        if (
            isinstance(content, str)
            or isinstance(content, bytearray)
            or isinstance(content, bytes)
        ):
            return json.loads(content)
        else:
            return content


PinotHTTPDialect = PinotDialect


class PinotHTTPSDialect(PinotDialect):
    scheme = "https"


class PinotMultiStageDialect(PinotDialect):
    engine_type = "multi_stage"


class PinotHTTPSMultiStageDialect(PinotDialect):
    engine_type = "multi_stage"
    scheme = "https"


class PinotAsyncDialect(PinotDialect):
    driver = "rest_async"
    is_async = True
    supports_statement_cache = False

    @classmethod
    def get_pool_class(cls, url):
        return pool.AsyncAdaptedQueuePool

    @classmethod
    def dbapi(cls):
        return _PINOT_ASYNC_DBAPI

    @classmethod
    def import_dbapi(cls):
        return _PINOT_ASYNC_DBAPI


PinotHTTPAsyncDialect = PinotAsyncDialect


class PinotHTTPSAsyncDialect(PinotAsyncDialect):
    scheme = "https"


class PinotMultiStageAsyncDialect(PinotAsyncDialect):
    engine_type = "multi_stage"


class PinotHTTPSMultiStageAsyncDialect(PinotAsyncDialect):
    engine_type = "multi_stage"
    scheme = "https"


def get_default(pinot_column_default):
    if pinot_column_default == "null":
        return None
    else:
        return str(pinot_column_default)


# Ref to supported Pinot data types:
# https://docs.pinot.apache.org/basics/components/schema#data-types
def get_type(data_type, field_size):
    type_map = {
        "int": types.BigInteger,
        "long": types.BigInteger,
        "float": types.Float,
        "double": types.Numeric,
        "big_decimal": types.Numeric,
        # BOOLEAN, is added after release 0.7.1.
        # In release 0.7.1 and older releases, BOOLEAN is equivalent to STRING.
        "boolean": types.Boolean,
        "timestamp": types.TIMESTAMP,
        "string": types.String,
        "json": types.JSON,
        "bytes": types.LargeBinary,
        # Complex types
        "struct": types.BLOB,
        "map": types.BLOB,
        "array": types.ARRAY,
    }
    return type_map[data_type.lower()]
