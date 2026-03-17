---
title: Getting Started
layout: default
nav_order: 2
---

# Getting Started
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Installation

Install from PyPI:

```bash
pip install pinotdb
```

To include SQLAlchemy support:

```bash
pip install pinotdb[sqlalchemy]
```

## Prerequisites

You need a running Apache Pinot cluster. The quickest way to get started is with Docker:

```bash
docker run --name pinot-quickstart \
  -p 2123:2123 -p 9000:9000 -p 8000:8000 \
  -d apachepinot/pinot:latest QuickStart -type batch
```

This starts a Pinot cluster with:

| Component  | Port |
|------------|------|
| Zookeeper  | 2123 |
| Controller | 9000 |
| Broker     | 8000 |

## Quick Start with DB-API

```python
from pinotdb import connect

conn = connect(host='localhost', port=8000, path='/query/sql', scheme='http')
curs = conn.cursor()
curs.execute("SELECT * FROM baseballStats LIMIT 5")
for row in curs:
    print(row)
```

## Quick Start with SQLAlchemy

```python
from sqlalchemy import create_engine, text

engine = create_engine(
    'pinot://localhost:8099/query/sql?controller=http://localhost:9000/'
)

with engine.connect() as connection:
    result = connection.execute(text("SELECT count(*) FROM baseballStats"))
    print(result.scalar())
```

## What's Next?

- [DB-API Guide]({% link db-api.md %}) -- Learn about the DB-API interface in detail
- [SQLAlchemy Guide]({% link sqlalchemy.md %}) -- Use SQLAlchemy ORM with Pinot
- [Examples]({% link examples.md %}) -- Browse runnable example scripts
