# Python DB-API and SQLAlchemy dialect for Pinot

This module allows accessing Pinot via its [SQL API](https://docs.pinot.apache.org/users/user-guide-query/pinot-query-language).

Current supported Pinot version: `1.1.0`.

## Usage

### Using the DB API to query Pinot Broker directly:

```python
from pinotdb import connect

# this assumes 8000 is the broker port
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

For HTTPS:

```python
from pinotdb import connect

# this assumes that 443 is the broker secure https port
conn = connect(host='localhost', port=443, path='/query/sql', scheme='https')
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

Pinot also supports basic auth, e.g.

```python
conn = connect(host="localhost", port=443, path="/query/sql", scheme="https", username="my-user", password="my-password", verify_ssl=True)
```

To pass in additional query parameters (such as `useMultistageEngine=true`) you may pass
them in as part of the `execute` method. For example:

```python
curs.execute("select * from airlineStats air limit 10", queryOptions="useMultistageEngine=true")
```

Broker query stats are exposed after `execute()` on `cursor.query_stats`:

```python
curs.execute("select * from airlineStats air limit 10")
print(curs.query_stats.get("numServersQueried"))
print(curs.query_stats.get("numDocsScanned"))
print(curs.timeUsedMs)  # Backward compatible shorthand
```

`cursor.query_stats` contains scalar top-level metrics returned by the broker
for the latest `execute()` or `execute_native()` call (sync and async).
Common keys include:

- `numServersQueried`
- `numServersResponded`
- `numSegmentsQueried`
- `numSegmentsProcessed`
- `numSegmentsMatched`
- `numConsumingSegmentsQueried`
- `numDocsScanned`
- `numEntriesScannedInFilter`
- `numEntriesScannedPostFilter`
- `numGroupsLimitReached`
- `totalDocs`
- `timeUsedMs`
- `minConsumingFreshnessTimeMs`
- `numSegmentsPrunedByBroker`

`cursor.query_statistics` also retains nested and list-valued statistics such
as `stageStats`, `earlyTerminationReasons`, `tablesQueried`, and future broker
metrics. Both statistics dictionaries exclude result rows, query errors, and
`traceInfo`. For the full payload, use
`cursor.raw_query_response["response"]`.

### Native query results (9.2+)

`execute_native()` returns a `NativeQueryResult` with column names, native column
types, row arrays, exceptions, and typed execution metadata. TIMESTAMP and JSON
values retain their native strings; duplicate column aliases remain separate
columns. Read `result.rows` directly: `fetchall()` belongs to the DB-API
`execute()` path.

```python
import httpx
from pinotdb import connect

sql = "SELECT playerID, yearID FROM baseballStats WHERE yearID >= %(year)s LIMIT 5"
with connect(host="localhost", port=8000) as cursor:
    result = cursor.execute_native(
        sql,
        {"year": 2010},
        query_options="timeoutMs=4000;clientQueryId=example-native",
        timeout=httpx.Timeout(5.0, connect=1.0),
    )
    print(result.metadata.completeness, result.columns, len(result.rows))
    stage_stats = cursor.query_statistics.get("stageStats", {})
    native_payload = result.raw_response
```

By default, partial or unknown execution raises `DatabaseError`; its
`native_result` attribute retains the decoded evidence. To inspect that evidence
without rejecting partial execution, pass `allow_partial=True` and check both
`result.metadata.completeness` and `result.exceptions` before using the rows:

```python
with connect(host="localhost", port=8000) as cursor:
    result = cursor.execute_native(sql, {"year": 2010}, allow_partial=True)
    print(result.metadata.unknown_reasons)
    print(result.metadata.execution_limit_flags)
```

The async API has the same arguments and result:

```python
from pinotdb import connect_async

async def query_native():
    async with connect_async(host="localhost", port=8000) as cursor:
        return await cursor.execute_native(
            sql, {"year": 2010}, allow_partial=True,
            timeout=httpx.Timeout(5.0, connect=1.0),
        )
```

Missing result tables or required metadata remain `unknown`; a complete empty
result retains its schema. Complete execution describes the submitted SQL, not
full dataset coverage or rows beyond its LIMIT. Per-call HTTPX timeouts bound
network phases; they do not guarantee an overall deadline or native cancellation.
Native calls do not retry automatically. See
[the runnable sync/async example](examples/native_query.py): run
`python examples/native_query.py`, or add `--async` for the async cursor.

#### Pass the Pinot database context

> [!IMPORTANT]
> This feature is only available from [5.1.5](https://pypi.org/project/pinotdb/5.1.5/)

```python
from pinotdb import connect

# this assumes that 443 is the broker secure https port
conn = connect(host='localhost', port=8000, path='/query/sql', scheme='http', database='dbName')
curs = conn.cursor()
curs.execute("""
    SELECT col1 from table1 LIMIT 10
""")
for row in curs:
    print(row)
```

where,

- `dbName` : the database context that needs to be passed
- `table1` : table under the `dbName` database

If `database` is not specified the connection will use the `default` database context.

### Using SQLAlchemy:

Since db engine requires more information beyond Pinot Broker, you need to provide pinot controller for table and schema information.

The db engine connection string is format as:

```
pinot+<pinot-broker-protocol>://<pinot-broker-host>:<pinot-broker-port><pinot-broker-path>?controller=<pinot-controller-protocol>://<pinot-controller-host>:<pinot-controller-port>/
```

Default scheme is HTTP so you can ignore it. e.g. `pinot+http://localhost:8099/query/sql?controller=http://localhost:9000/` and `pinot://localhost:8099/query/sql?controller=localhost:9000/` work in same way.

For HTTPS, you have to specify the `https` scheme explicitly along with the port.

```
pinot+https://<pinot-broker-host>:<pinot-broker-port><pinot-broker-path>?controller=https://<pinot-controller-host>:<pinot-controller-port>/
```

E.g. `pinot+https://pinot-broker.pinot.live:443/query/sql?controller=https://pinot-controller.pinot.live/`.

Please note that the broker port 443 has to be explicitly put there.

This can be used as Superset to Pinot connection:

<img title="Superset Pinot Connection" src="assets/images/screenshots/superset-connection.png"/>

If you have basic auth:

```
pinot+https://<my-user>:<my-password>@<pinot-broker-host>:<pinot-broker-port><pinot-broker-path>?controller=https://<pinot-controller-host>:<pinot-controller-port>/[&&verify_ssl=<true/false>]
```

E.g.
`pinot+https://my-user:my-password@my-secure-pinot-broker:443/query/sql?controller=https://my-secure-pinot-controller/&&verify_ssl=true`.

Below are some sample scripts to query pinot using SQLAlchemy 2.x:

```python
from sqlalchemy import *
from sqlalchemy.engine import create_engine
from sqlalchemy.schema import *

engine = create_engine('pinot://localhost:8099/query/sql?controller=http://localhost:9000/')  # uses HTTP by default :(
# or, using explicit HTTP:
# engine = create_engine('pinot+http://localhost:8099/query/sql?controller=http://localhost:9000/')
# or, using explicit HTTPS:
# engine = create_engine('pinot+https://localhost:8099/query/sql?controller=https://localhost:9000/')
# or, provide extra argument to connect with multi-stage engine enabled:
# engine = create_engine(
#     "pinot://localhost:8000/query/sql?controller=http://localhost:9000/",
#     connect_args={"use_multistage_engine": "true"}
# )

metadata = MetaData()
places = Table('places', metadata, autoload_with=engine)
query = select(func.count()).select_from(places)
with engine.connect() as connection:
    print(connection.execute(query).scalar())
```

For asyncio support with SQLAlchemy `create_async_engine`, use the async
dialect:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    "pinot+async://localhost:8000/query/sql?controller=http://localhost:9000/"
)
# or, using explicit async HTTPS:
# engine = create_async_engine(
#     "pinot+https_async://localhost:443/query/sql?controller=https://localhost:9000/"
# )

async with engine.connect() as connection:
    result = await connection.execute(text("SELECT * FROM baseballStats LIMIT 5"))
    print(result.fetchall())
```

To configure query parameters (such as `timeoutMs=10000`) at the engine level
you may pass them while creating the engine. For example:

```python
engine = create_engine(
        "pinot://localhost:8000/query/sql?controller=http://localhost:9000/",
        connect_args={"query_options": "use_multistage_engine=true;timeoutMs=10000"})
```

To support multi-stage engine, you can pass the `use_multistage_engine` parameter in the `connect_args` dictionary.

E.g. In SuperSet Engine Parameters, you can put the following JSON:

```
{"connect_args":{"use_multistage_engine":"true"}}
```

#### Pass the Pinot database context

> [!IMPORTANT]
> This feature is only available from [5.1.5](https://pypi.org/project/pinotdb/5.1.5/)

Each connection should only query one Pinot Database, hence we provide that context through connection string itself.

The db engine connection string is format as:

```
pinot+http://pinot-broker:8099/query/sql?controller=http://pinot-controller:9000/&database=dbName
```

where `dbName` is the database context that needs to be passed.
If not specified the connection will use the `default` database context while querying.

## Examples with Pinot Quickstart

Start Pinot Batch Quickstart

```bash
docker run --name pinot-quickstart -p 2123:2123 -p 9000:9000 -p 8000:8000 -d apachepinot/pinot:latest QuickStart -type batch
```

Once pinot batch quickstart is up, you can run below sample code snippet to query Pinot:

```bash
python3 examples/pinot_quickstart_batch.py
```

Sample Output:

```
Sending SQL to Pinot: SELECT * FROM baseballStats LIMIT 5
[0, 11, 0, 0, 0, 0, 0, 0, 0, 0, 'NL', 11, 11, 'aardsda01', 'David Allan', 1, 0, 0, 0, 0, 0, 0, 'SFN', 0, 2004]
[2, 45, 0, 0, 0, 0, 0, 0, 0, 0, 'NL', 45, 43, 'aardsda01', 'David Allan', 1, 0, 0, 0, 1, 0, 0, 'CHN', 0, 2006]
[0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 'AL', 25, 2, 'aardsda01', 'David Allan', 1, 0, 0, 0, 0, 0, 0, 'CHA', 0, 2007]
[1, 5, 0, 0, 0, 0, 0, 0, 0, 0, 'AL', 47, 5, 'aardsda01', 'David Allan', 1, 0, 0, 0, 0, 0, 1, 'BOS', 0, 2008]
[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 'AL', 73, 3, 'aardsda01', 'David Allan', 1, 0, 0, 0, 0, 0, 0, 'SEA', 0, 2009]

Sending SQL to Pinot: SELECT playerName, sum(runs) FROM baseballStats WHERE yearID>=2000 GROUP BY playerName LIMIT 5
['Scott Michael', 26.0]
['Justin Morgan', 0.0]
['Jason Andre', 0.0]
['Jeffrey Ellis', 0.0]
['Maximiliano R.', 16.0]

Sending SQL to Pinot: SELECT playerName,sum(runs) AS sum_runs FROM baseballStats WHERE yearID>=2000 GROUP BY playerName ORDER BY sum_runs DESC LIMIT 5
['Adrian', 1820.0]
['Jose Antonio', 1692.0]
['Rafael', 1565.0]
['Brian Michael', 1500.0]
['Alexander Emmanuel', 1426.0]
```

Start Pinot Hybrid Quickstart

```bash
docker run --name pinot-quickstart -p 2123:2123 -p 9000:9000 -p 8000:8000 -d apachepinot/pinot:latest QuickStart -type hybrid
```

Below is an example against Pinot Quickstart Hybrid:

```bash
python3 examples/pinot_quickstart_hybrid.py
```

```bash
Sending SQL to Pinot: SELECT * FROM airlineStats LIMIT 5
[171, 153, 19393, 0, 8, 8, 1433, '1400-1459', 0, 1425, 1240, 165, 'null', 0, 'WN', -2147483648, 1, 27, 17540, 0, 2, 2, 1242, '1200-1259', 0, 'MDW', 13232, 1323202, 30977, 'Chicago, IL', 'IL', 17, 'Illinois', 41, 861, 4, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-27', 402, 1, -2147483648, -2147483648, 1, -2147483648, 'BOS', 10721, 1072102, 30721, 'Boston, MA', 'MA', 25, 'Massachusetts', 13, 1, ['null'], -2147483648, 'N556WN', 6, 12, -2147483648, 'WN', -2147483648, 1254, 1427, 2014]
[183, 141, 20398, 1, 17, 17, 1302, '1200-1259', 1, 1245, 1005, 160, 'null', 0, 'MQ', 0, 1, 27, 17540, 0, -6, 0, 959, '1000-1059', -1, 'CMH', 11066, 1106603, 31066, 'Columbus, OH', 'OH', 39, 'Ohio', 44, 990, 4, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-27', 3574, 1, 0, -2147483648, 1, 17, 'MIA', 13303, 1330303, 32467, 'Miami, FL', 'FL', 12, 'Florida', 33, 1, ['null'], 0, 'N605MQ', 13, 29, -2147483648, 'MQ', 0, 1028, 1249, 2014]
[-2147483648, -2147483648, 20304, -2147483648, -2147483648, -2147483648, -2147483648, '2100-2159', -2147483648, 2131, 2005, 146, 'null', 0, 'OO', -2147483648, 1, 27, 17541, 1, 52, 52, 2057, '2000-2059', 3, 'COS', 11109, 1110902, 30189, 'Colorado Springs, CO', 'CO', 8, 'Colorado', 82, 809, 4, -2147483648, [11292], 1, [1129202], ['DEN'], -2147483648, 73, [9], 0, ['null'], [9], [-2147483648], [2304], 1, -2147483648, '2014-01-27', 5554, 1, -2147483648, -2147483648, 1, -2147483648, 'IAH', 12266, 1226603, 31453, 'Houston, TX', 'TX', 48, 'Texas', 74, 1, ['SEA', 'PSC', 'PHX', 'MSY', 'ATL', 'TYS', 'DEN', 'CHS', 'PDX', 'LAX', 'EWR', 'SFO', 'PIT', 'RDU', 'RAP', 'LSE', 'SAN', 'SBN', 'IAH', 'OAK', 'BRO', 'JFK', 'SAT', 'ORD', 'ACY', 'DFW', 'BWI'], -2147483648, 'N795SK', -2147483648, 19, -2147483648, 'OO', -2147483648, 2116, -2147483648, 2014]
[153, 125, 20436, 1, 41, 41, 1442, '1400-1459', 2, 1401, 1035, 146, 'null', 0, 'F9', 2, 1, 27, 17541, 1, 34, 34, 1109, '1000-1059', 2, 'DEN', 11292, 1129202, 30325, 'Denver, CO', 'CO', 8, 'Colorado', 82, 967, 4, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-27', 658, 1, 8, -2147483648, 1, 31, 'SFO', 14771, 1477101, 32457, 'San Francisco, CA', 'CA', 6, 'California', 91, 1, ['null'], 0, 'N923FR', 11, 17, -2147483648, 'F9', 0, 1126, 1431, 2014]
[-2147483648, -2147483648, 20304, -2147483648, -2147483648, -2147483648, -2147483648, '1400-1459', -2147483648, 1432, 1314, 78, 'B', 1, 'OO', -2147483648, 1, 27, 17541, -2147483648, -2147483648, -2147483648, -2147483648, '1300-1359', -2147483648, 'EAU', 11471, 1147103, 31471, 'Eau Claire, WI', 'WI', 55, 'Wisconsin', 45, 268, 2, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-27', 5455, 1, -2147483648, -2147483648, 1, -2147483648, 'ORD', 13930, 1393003, 30977, 'Chicago, IL', 'IL', 17, 'Illinois', 41, 1, ['null'], -2147483648, 'N903SW', -2147483648, -2147483648, -2147483648, 'OO', -2147483648, -2147483648, -2147483648, 2014]

Sending SQL to Pinot: SELECT count(*) FROM airlineStats LIMIT 5
[17772]

Sending SQL to Pinot: SELECT AirlineID, sum(Cancelled) FROM airlineStats WHERE Year > 2010 GROUP BY AirlineID LIMIT 5
[20409, 40.0]
[19930, 16.0]
[19805, 60.0]
[19790, 115.0]
[20366, 172.0]

Sending SQL to Pinot: select OriginCityName, max(Flights) from airlineStats group by OriginCityName ORDER BY max(Flights) DESC LIMIT 5
['Casper, WY', 1.0]
['Deadhorse, AK', 1.0]
['Austin, TX', 1.0]
['Chicago, IL', 1.0]
['Monterey, CA', 1.0]

Sending SQL to Pinot: SELECT OriginCityName, sum(Cancelled) AS sum_cancelled FROM airlineStats WHERE Year>2010 GROUP BY OriginCityName ORDER BY sum_cancelled DESC LIMIT 5
['Chicago, IL', 178.0]
['Atlanta, GA', 111.0]
['New York, NY', 65.0]
['Houston, TX', 62.0]
['Denver, CO', 49.0]

Sending Count(*) SQL to Pinot
17773

Sending SQL: "SELECT OriginCityName, sum(Cancelled) AS sum_cancelled FROM "airlineStats" WHERE Year>2010 GROUP BY OriginCityName ORDER BY sum_cancelled DESC LIMIT 5" to Pinot
[('Chicago, IL', 178.0), ('Atlanta, GA', 111.0), ('New York, NY', 65.0), ('Houston, TX', 62.0), ('Denver, CO', 49.0)]
```

## Examples with existing pinot.live demo cluster

Just run below script to query `pinot.live` demo cluster in two ways using pinotdb connect and sqlalchemy.

```bash
python3 examples/pinot_live.py
```

And response:

```bash
Sending SQL to Pinot: SELECT * FROM airlineStats LIMIT 5
[384, 359, 19805, 0, 13, 13, 1238, '1200-1259', 0, 1225, 900, 385, 'null', 0, 'AA', -2147483648, 3, 1, 16071, 0, 14, 14, 914, '0900-0959', 0, 'LAX', 12892, 1289203, 32575, 'Los Angeles, CA', 'CA', 6, 'California', 91, 2475, 10, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-01', 1, 1, -2147483648, -2147483648, 1, -2147483648, 'JFK', 12478, 1247802, 31703, 'New York, NY', 'NY', 36, 'New York', 22, 1, ['SEA', 'PSC', 'PHX', 'MSY', 'ATL', 'TYS', 'DEN', 'CHS', 'PDX', 'LAX', 'EWR', 'SFO', 'PIT', 'RDU', 'RAP', 'LSE', 'SAN', 'SBN', 'IAH', 'OAK', 'BRO', 'JFK', 'SAT', 'ORD', 'ACY', 'DFW', 'BWI', 'TPA', 'BFL', 'BOS', 'SNA', 'ISN'], -2147483648, 'N338AA', 5, 20, -2147483648, 'AA', -2147483648, 934, 1233, 2014]
[269, 251, 19805, 0, -36, 0, 1549, '1600-1659', -2, 1625, 825, 300, 'null', 0, 'AA', -2147483648, 3, 1, 16071, 0, -5, 0, 820, '0800-0859', -1, 'JFK', 12478, 1247802, 31703, 'New York, NY', 'NY', 36, 'New York', 22, 2248, 9, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-01', 44, 1, -2147483648, -2147483648, 1, -2147483648, 'LAS', 12889, 1288903, 32211, 'Las Vegas, NV', 'NV', 32, 'Nevada', 85, 1, ['SEA', 'PSC', 'PHX', 'MSY', 'ATL', 'TYS', 'DEN', 'CHS', 'PDX', 'LAX', 'EWR', 'SFO', 'PIT', 'RDU', 'RAP', 'LSE', 'SAN', 'SBN', 'IAH', 'OAK'], -2147483648, 'N3DVAA', 6, 12, -2147483648, 'AA', -2147483648, 832, 1543, 2014]
[307, 288, 19805, 0, -26, 0, 2039, '2100-2159', -2, 2105, 1340, 325, 'null', 0, 'AA', -2147483648, 3, 1, 16071, 0, -8, 0, 1332, '1300-1359', -1, 'LAX', 12892, 1289203, 32575, 'Los Angeles, CA', 'CA', 6, 'California', 91, 2556, 11, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-01', 162, 1, -2147483648, -2147483648, 1, -2147483648, 'HNL', 12173, 1217301, 32134, 'Honolulu, HI', 'HI', 15, 'Hawaii', 2, 1, ['SEA', 'PSC', 'PHX', 'MSY', 'ATL', 'TYS', 'DEN'], -2147483648, 'N5FCAA', 8, 11, -2147483648, 'AA', -2147483648, 1343, 2031, 2014]
[141, 126, 19805, 0, -19, 0, 1456, '1500-1559', -2, 1515, 1135, 160, 'null', 0, 'AA', -2147483648, 3, 1, 16071, 0, 0, 0, 1135, '1100-1159', 0, 'DCA', 11278, 1127802, 30852, 'Washington, DC', 'VA', 51, 'Virginia', 38, 1192, 5, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-01', 130, 1, -2147483648, -2147483648, 1, -2147483648, 'DFW', 11298, 1129803, 30194, 'Dallas/Fort Worth, TX', 'TX', 48, 'Texas', 74, 1, ['null'], -2147483648, 'N3EGAA', 4, 11, -2147483648, 'AA', -2147483648, 1146, 1452, 2014]
[300, 277, 19805, 0, -8, 0, 32, '0001-0559', -1, 40, 1625, 315, 'null', 0, 'AA', -2147483648, 3, 1, 16071, 0, 7, 7, 1632, '1600-1659', 0, 'JFK', 12478, 1247802, 31703, 'New York, NY', 'NY', 36, 'New York', 22, 2475, 10, -2147483648, [-2147483648], 0, [-2147483648], ['null'], -2147483648, -2147483648, [-2147483648], -2147483648, ['null'], [-2147483648], [-2147483648], [-2147483648], 0, -2147483648, '2014-01-01', 180, 1, -2147483648, -2147483648, 1, -2147483648, 'LAX', 12892, 1289203, 32575, 'Los Angeles, CA', 'CA', 6, 'California', 91, 1, ['null'], -2147483648, 'N335AA', 10, 13, -2147483648, 'AA', -2147483648, 1645, 22, 2014]

Sending Count(*) SQL to Pinot
9746

Sending SQL: "SELECT playerName, sum(runs) AS sum_runs FROM "baseballStats" WHERE yearID>=2000 GROUP BY playerName ORDER BY sum_runs DESC LIMIT 5" to Pinot
[(19790, 581.0), (19977, 522.0), (19690, 520.0), (19805, 481.0), (20409, 410.0), (21171, 385.0), (19930, 378.0), (20355, 377.0), (19393, 326.0), (20437, 268.0)]
```

## Development

In order to develop this library, you need to have installed Poetry and tox.

After you make sure you have them installed, test the library:

1. Run the Pinot QuickStart (for integration tests): `$ make run-pinot`
2. On a separate shell, run: `$ make init`
3. Then: `$ make test`
4. To generate unit test coverage reports: `$ make coverage`

## Release

The preferred release path is the GitHub Actions workflow:
[Pinotdb Pypi Publisher](https://github.com/startreedata/pinot-dbapi/actions/workflows/pinotdb-pypi-publisher.yml).

It will:

1. Check out the selected branch.
2. Bump `pyproject.toml` to the requested version.
3. Generate a changelog from the previous `release-*` tag.
4. Commit the version bump and create the `release-<version>` tag.
5. Create a GitHub Release.
6. Build and publish `pinotdb` to [PyPI](https://pypi.org/project/pinotdb/).

### GitHub Actions release workflow

Before using the workflow, make sure the repository has these GitHub Actions secrets:

1. `RELEASE_PAT`
2. `PYPI_USERNAME`
3. `PYPI_PASSWORD`

If you are publishing with a PyPI API token, set:

1. `PYPI_USERNAME=__token__`
2. `PYPI_PASSWORD=<your_api_token_generated_from_pypi.org>`

Then open the workflow page and click `Run workflow`.

Inputs:

1. `ref`: Branch to release from. Defaults to `master`.
2. `version`: Exact version to release, for example `9.0.1`.

Notes:

1. `ref` must be a branch name on `origin`. The workflow commits the version bump back to that branch before creating the release tag.
2. The release tag format is `release-<version>`.
3. `RELEASE_PAT` must be able to push to the protected release branch, for example `master`.

### Manual release

If you need to release manually instead of using GitHub Actions, you can still do it locally.

If you are using a PyPI API token with Poetry:

```
$ poetry config pypi-token.pypi <your_api_token_generated_from_pypi.org>
```

Or publish with username and password:

```
$ poetry publish --username=<your_username> --password='<your_password>'
```

Then run the release steps:

```bash
$ BRANCH=master
$ VERSION=<new_version>
$ poetry version "$VERSION"
$ PINOTDB_VERSION=$(poetry version -s)
$ poetry build
$ poetry publish
$ git add pyproject.toml
$ git commit -m "Update version to pinotdb ${PINOTDB_VERSION}"
$ git tag "release-${PINOTDB_VERSION}"
$ git push origin "HEAD:${BRANCH}"
$ git push origin "release-${PINOTDB_VERSION}"
$ gh release create "release-${PINOTDB_VERSION}" \
    --title "Release release-${PINOTDB_VERSION}" \
    --generate-notes
```
