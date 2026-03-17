---
title: DB-API Guide
layout: default
nav_order: 3
---

# DB-API Guide
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

pinotdb implements the [Python DB-API 2.0 specification (PEP 249)](https://peps.python.org/pep-0249/) for querying Apache Pinot Broker directly.

## Basic Connection

```python
from pinotdb import connect

conn = connect(host='localhost', port=8000, path='/query/sql', scheme='http')
curs = conn.cursor()
curs.execute("""
    SELECT place,
           CAST(REGEXP_EXTRACT(place, '(.*),', 1) AS FLOAT) AS lat,
           CAST(REGEXP_EXTRACT(place, ',(.*)', 1) AS FLOAT) AS lon
      FROM places
     LIMIT 10
""")
for row in curs:
    print(row)
```

## HTTPS Connection

```python
from pinotdb import connect

conn = connect(host='localhost', port=443, path='/query/sql', scheme='https')
curs = conn.cursor()
curs.execute("SELECT * FROM places LIMIT 10")
for row in curs:
    print(row)
```

## Authentication

pinotdb supports basic auth:

```python
conn = connect(
    host="localhost",
    port=443,
    path="/query/sql",
    scheme="https",
    username="my-user",
    password="my-password",
    verify_ssl=True
)
```

## Query Options

Pass additional query parameters (such as `useMultistageEngine=true`) via the `execute` method:

```python
curs.execute(
    "SELECT * FROM airlineStats LIMIT 10",
    queryOptions="useMultistageEngine=true"
)
```

## Query Statistics

After calling `execute()`, broker query stats are available on `cursor.query_stats`:

```python
curs.execute("SELECT * FROM airlineStats LIMIT 10")
print(curs.query_stats.get("numServersQueried"))
print(curs.query_stats.get("numDocsScanned"))
print(curs.timeUsedMs)  # Backward compatible shorthand
```

`cursor.query_stats` contains scalar top-level metrics returned by the broker. Common keys include:

| Key | Description |
|-----|-------------|
| `numServersQueried` | Number of servers queried |
| `numServersResponded` | Number of servers that responded |
| `numSegmentsQueried` | Number of segments queried |
| `numSegmentsProcessed` | Number of segments processed |
| `numSegmentsMatched` | Number of segments matched |
| `numConsumingSegmentsQueried` | Number of consuming segments queried |
| `numDocsScanned` | Number of documents scanned |
| `numEntriesScannedInFilter` | Number of entries scanned in filter |
| `numEntriesScannedPostFilter` | Number of entries scanned post filter |
| `numGroupsLimitReached` | Whether group limit was reached |
| `totalDocs` | Total number of documents |
| `timeUsedMs` | Query execution time in milliseconds |
| `minConsumingFreshnessTimeMs` | Minimum consuming freshness time |
| `numSegmentsPrunedByBroker` | Number of segments pruned by broker |

## Raw Query Response

If you need the full broker payload (including nested sections such as `resultTable`, `exceptions`, and tracing information), use:

```python
cursor.raw_query_response
```

## Database Context

{: .important }
> This feature is only available from [pinotdb 5.1.5](https://pypi.org/project/pinotdb/5.1.5/) onwards.

You can specify a Pinot database context when connecting:

```python
from pinotdb import connect

conn = connect(
    host='localhost',
    port=8000,
    path='/query/sql',
    scheme='http',
    database='dbName'
)
curs = conn.cursor()
curs.execute("SELECT col1 FROM table1 LIMIT 10")
for row in curs:
    print(row)
```

- `dbName` -- the database context to use
- `table1` -- a table under the `dbName` database

If `database` is not specified, the connection uses the `default` database context.
