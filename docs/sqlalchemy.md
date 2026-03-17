---
title: SQLAlchemy Guide
layout: default
nav_order: 4
---

# SQLAlchemy Guide
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

pinotdb provides a SQLAlchemy dialect so you can query Apache Pinot using familiar SQLAlchemy APIs. Since the db engine requires more information beyond Pinot Broker, you need to provide the Pinot Controller URL for table and schema information.

## Connection String Format

```
pinot+<protocol>://<broker-host>:<broker-port><broker-path>?controller=<controller-url>/
```

### Supported Dialects

| Dialect | Protocol | Description |
|---------|----------|-------------|
| `pinot` | HTTP | Default, same as `pinot+http` |
| `pinot+http` | HTTP | Explicit HTTP |
| `pinot+https` | HTTPS | Secure HTTPS |
| `pinot+async` | HTTP (async) | Asyncio over HTTP |
| `pinot+https_async` | HTTPS (async) | Asyncio over HTTPS |

## Basic Usage

```python
from sqlalchemy import *
from sqlalchemy.engine import create_engine
from sqlalchemy.schema import *

engine = create_engine(
    'pinot://localhost:8099/query/sql?controller=http://localhost:9000/'
)

metadata = MetaData()
places = Table('places', metadata, autoload_with=engine)
query = select(func.count()).select_from(places)

with engine.connect() as connection:
    print(connection.execute(query).scalar())
```

## HTTPS

For HTTPS, specify the `https` scheme explicitly along with the port:

```
pinot+https://<broker-host>:<broker-port><broker-path>?controller=https://<controller-host>:<controller-port>/
```

Example:

```python
engine = create_engine(
    'pinot+https://pinot-broker.pinot.live:443/query/sql'
    '?controller=https://pinot-controller.pinot.live/'
)
```

{: .important }
> The broker port (e.g. `443`) must be specified explicitly in the connection string.

## Authentication

Include credentials in the connection string:

```
pinot+https://<user>:<password>@<broker-host>:<broker-port><broker-path>?controller=https://<controller-host>:<controller-port>/[&&verify_ssl=<true/false>]
```

Example:

```python
engine = create_engine(
    'pinot+https://my-user:my-password@my-secure-broker:443/query/sql'
    '?controller=https://my-secure-controller/&&verify_ssl=true'
)
```

## Async Support

For asyncio support, use `create_async_engine` with the async dialect:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    "pinot+async://localhost:8000/query/sql?controller=http://localhost:9000/"
)

async with engine.connect() as connection:
    result = await connection.execute(
        text("SELECT * FROM baseballStats LIMIT 5")
    )
    print(result.fetchall())
```

For HTTPS async:

```python
engine = create_async_engine(
    "pinot+https_async://localhost:443/query/sql"
    "?controller=https://localhost:9000/"
)
```

## Query Options

Configure query parameters at the engine level via `connect_args`:

```python
engine = create_engine(
    "pinot://localhost:8000/query/sql?controller=http://localhost:9000/",
    connect_args={
        "query_options": "use_multistage_engine=true;timeoutMs=10000"
    }
)
```

### Multi-Stage Engine

Enable the multi-stage query engine:

```python
engine = create_engine(
    "pinot://localhost:8000/query/sql?controller=http://localhost:9000/",
    connect_args={"use_multistage_engine": "true"}
)
```

In Apache Superset, configure this via the **Engine Parameters** field:

```json
{"connect_args": {"use_multistage_engine": "true"}}
```

## Superset Integration

pinotdb works with [Apache Superset](https://superset.apache.org/). Use the SQLAlchemy connection string as the database URL in Superset's data source configuration:

![Superset Pinot Connection]({{ site.baseurl }}/assets/images/screenshots/superset-connection.png)

## Database Context

{: .important }
> This feature is only available from [pinotdb 5.1.5](https://pypi.org/project/pinotdb/5.1.5/) onwards.

Each connection targets one Pinot database. Provide the database context in the connection string:

```
pinot+http://pinot-broker:8099/query/sql?controller=http://pinot-controller:9000/&database=dbName
```

If not specified, the connection uses the `default` database context.
