---
title: Examples
layout: default
nav_order: 5
---

# Examples
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

The repository includes several runnable example scripts in the [`examples/`](https://github.com/startreedata/pinot-dbapi/tree/master/examples) directory.

## Pinot Batch Quickstart

Start a Pinot batch quickstart cluster:

```bash
docker run --name pinot-quickstart \
  -p 2123:2123 -p 9000:9000 -p 8000:8000 \
  -d apachepinot/pinot:latest QuickStart -type batch
```

Run the example:

```bash
python3 examples/pinot_quickstart_batch.py
```

Sample output:

```
Sending SQL to Pinot: SELECT * FROM baseballStats LIMIT 5
[0, 11, 0, 0, 0, 0, 0, 0, 0, 0, 'NL', 11, 11, 'aardsda01', 'David Allan', ...]

Sending SQL to Pinot: SELECT playerName, sum(runs) FROM baseballStats
    WHERE yearID>=2000 GROUP BY playerName LIMIT 5
['Scott Michael', 26.0]
['Justin Morgan', 0.0]
...

Sending SQL to Pinot: SELECT playerName,sum(runs) AS sum_runs FROM baseballStats
    WHERE yearID>=2000 GROUP BY playerName ORDER BY sum_runs DESC LIMIT 5
['Adrian', 1820.0]
['Jose Antonio', 1692.0]
['Rafael', 1565.0]
...
```

## Pinot Hybrid Quickstart

Start a Pinot hybrid quickstart cluster:

```bash
docker run --name pinot-quickstart \
  -p 2123:2123 -p 9000:9000 -p 8000:8000 \
  -d apachepinot/pinot:latest QuickStart -type hybrid
```

Run the example:

```bash
python3 examples/pinot_quickstart_hybrid.py
```

This demonstrates queries against airline data including aggregations and grouping.

## Multi-Stage Engine

```bash
python3 examples/pinot_quickstart_multi_stage.py
```

Demonstrates querying with Pinot's multi-stage query engine enabled via `queryOptions`.

## JSON Index Queries

```bash
python3 examples/pinot_quickstart_json_batch.py
```

Shows how to query JSON-indexed columns in Pinot.

## Authentication with Zookeeper

```bash
python3 examples/pinot_quickstart_auth_zk.py
```

Demonstrates connecting to a Pinot cluster with authentication and Zookeeper-based broker discovery.

## Query Timeout

```bash
python3 examples/pinot_quickstart_timeout.py
```

Shows how to configure query timeout options.

## Async Queries

```bash
python3 examples/pinot_async.py
```

Demonstrates async query execution using `create_async_engine` and `pinot+async` dialect.

## Pinot Live Demo

Query the public `pinot.live` demo cluster (no local Pinot required):

```bash
python3 examples/pinot_live.py
```

This example connects to the public demo cluster and runs queries using both DB-API and SQLAlchemy.
