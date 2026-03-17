---
title: API Reference
layout: default
nav_order: 6
---

# API Reference
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## pinotdb Module

### `connect()`

Create a synchronous DB-API connection to a Pinot Broker.

```python
from pinotdb import connect

conn = connect(
    host='localhost',
    port=8000,
    path='/query/sql',
    scheme='http',
    extra_request_headers=None,
    database='default',
    username=None,
    password=None,
    verify_ssl=True
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | `str` | `'localhost'` | Pinot Broker hostname |
| `port` | `int` | `8000` | Pinot Broker port |
| `path` | `str` | `'/query/sql'` | Broker query endpoint path |
| `scheme` | `str` | `'http'` | Protocol (`'http'` or `'https'`) |
| `extra_request_headers` | `dict` | `None` | Additional HTTP headers |
| `database` | `str` | `'default'` | Pinot database context |
| `username` | `str` | `None` | Basic auth username |
| `password` | `str` | `None` | Basic auth password |
| `verify_ssl` | `bool` | `True` | Whether to verify SSL certificates |

**Returns:** A `Connection` object.

---

### `connect_async()`

Create an asynchronous DB-API connection to a Pinot Broker.

```python
from pinotdb import connect_async

conn = await connect_async(
    host='localhost',
    port=8000,
    path='/query/sql',
    scheme='http',
    extra_request_headers=None,
    database='default',
    username=None,
    password=None,
    verify_ssl=True
)
```

Takes the same parameters as `connect()`.

**Returns:** An `AsyncConnection` object.

---

## Connection

### `Connection.cursor()`

Create a new cursor for executing queries.

```python
curs = conn.cursor()
```

**Returns:** A `Cursor` object.

### `Connection.close()`

Close the connection.

### `Connection.commit()`

No-op (Pinot is read-only via this interface).

---

## Cursor

### `Cursor.execute(query, queryOptions=None)`

Execute a SQL query against the Pinot Broker.

```python
curs.execute("SELECT * FROM myTable LIMIT 10")
curs.execute(
    "SELECT * FROM myTable LIMIT 10",
    queryOptions="useMultistageEngine=true"
)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `str` | SQL query string |
| `queryOptions` | `str` | Optional Pinot query options |

### `Cursor.fetchone()`

Fetch the next row from the result set.

**Returns:** A single row as a list, or `None` if no more rows.

### `Cursor.fetchmany(size=None)`

Fetch multiple rows from the result set.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `size` | `int` | Number of rows to fetch. Defaults to `cursor.arraysize`. |

**Returns:** A list of rows.

### `Cursor.fetchall()`

Fetch all remaining rows from the result set.

**Returns:** A list of all remaining rows.

### Cursor Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `description` | `list` | Column metadata (name, type, etc.) per DB-API spec |
| `rowcount` | `int` | Number of rows returned |
| `query_stats` | `dict` | Broker query statistics from the latest `execute()` |
| `timeUsedMs` | `int` | Shorthand for query execution time |
| `raw_query_response` | `dict` | Full broker JSON response |

---

## SQLAlchemy Dialects

pinotdb registers the following SQLAlchemy dialects:

| Entry Point | Dialect Class | Description |
|-------------|---------------|-------------|
| `pinot` | `PinotHTTPDialect` | HTTP (default) |
| `pinot.http` | `PinotHTTPDialect` | Explicit HTTP |
| `pinot.https` | `PinotHTTPSDialect` | HTTPS |
| `pinot.async` | `PinotAsyncDialect` | Async HTTP |
| `pinot.https_async` | `PinotHTTPSAsyncDialect` | Async HTTPS |

### Connection String Format

```
pinot+<protocol>://<host>:<port><path>?controller=<controller-url>/
```

### Engine `connect_args`

| Key | Type | Description |
|-----|------|-------------|
| `use_multistage_engine` | `str` | Set to `"true"` to enable multi-stage engine |
| `query_options` | `str` | Semicolon-separated Pinot query options |

---

## Exceptions

pinotdb defines the following exception hierarchy per DB-API 2.0:

| Exception | Parent | Description |
|-----------|--------|-------------|
| `Warning` | `Exception` | Important warnings |
| `Error` | `Exception` | Base error class |
| `InterfaceError` | `Error` | Interface-related errors |
| `DatabaseError` | `Error` | Database-related errors |
| `DataError` | `DatabaseError` | Data processing errors |
| `OperationalError` | `DatabaseError` | Operational errors |
| `IntegrityError` | `DatabaseError` | Integrity constraint violations |
| `InternalError` | `DatabaseError` | Internal database errors |
| `ProgrammingError` | `DatabaseError` | Programming errors |
| `NotSupportedError` | `DatabaseError` | Unsupported operations |
