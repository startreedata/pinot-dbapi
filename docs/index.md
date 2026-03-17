---
title: Home
layout: home
nav_order: 1
---

# pinotdb
{: .fs-9 }

Python DB-API 2.0 and SQLAlchemy dialect for Apache Pinot.
{: .fs-6 .fw-300 }

[Get Started]({% link getting-started.md %}){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 }
[View on GitHub](https://github.com/startreedata/pinot-dbapi){: .btn .fs-5 .mb-4 .mb-md-0 }
[PyPI](https://pypi.org/project/pinotdb/){: .btn .fs-5 .mb-4 .mb-md-0 }

---

**pinotdb** provides a standard Python [DB-API 2.0](https://peps.python.org/pep-0249/) interface and a [SQLAlchemy](https://www.sqlalchemy.org/) dialect for querying [Apache Pinot](https://pinot.apache.org/) via its SQL API.

Current supported Pinot version: **1.1.0**
{: .fs-5 }

## Key Features

- **DB-API 2.0 compliant** -- Use the familiar Python database API to query Pinot Broker directly
- **SQLAlchemy dialect** -- Full support for SQLAlchemy 2.0+ with multiple protocol variants (`pinot`, `pinot+http`, `pinot+https`)
- **Async support** -- First-class asyncio support via `pinot+async` and `pinot+https_async` dialects
- **Query statistics** -- Access broker query stats (`numDocsScanned`, `timeUsedMs`, etc.) after every query
- **Authentication** -- Basic auth with username/password
- **SSL/TLS** -- HTTPS connections with configurable SSL verification
- **Multi-stage engine** -- Support for Pinot's multi-stage query engine
- **Database context** -- Target specific Pinot databases per connection

## Quick Example

```python
from pinotdb import connect

conn = connect(host='localhost', port=8000, path='/query/sql', scheme='http')
curs = conn.cursor()
curs.execute("SELECT * FROM myTable LIMIT 10")
for row in curs:
    print(row)
```

## Supported Python Versions

| Python | Status |
|--------|--------|
| 3.10   | Supported |
| 3.11   | Supported |
| 3.12   | Supported |
| 3.13   | Supported |
| 3.14   | Supported |

## License

pinotdb is distributed under the [MIT License](https://github.com/startreedata/pinot-dbapi/blob/master/LICENSE).
