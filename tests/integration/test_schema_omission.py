"""Run against the real baseballStats Pinot quickstart fixture."""
import os

import pytest
from sqlalchemy import (
    MetaData, Table, create_engine, func, inspect, select, text,
)


@pytest.fixture(params=['pinot', 'pinot+http'])
def engine(request):
    host = os.getenv('PINOT_HOST', 'localhost')
    broker = os.getenv('PINOT_BROKER_PORT', '8000')
    controller = os.getenv('PINOT_CONTROLLER_PORT', '9000')
    engine = create_engine(
        f'{request.param}://{host}:{broker}/query/sql'
        f'?controller=http://{host}:{controller}/', pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        engine.dispose()


def test_inspector_has_table(engine):
    inspector = inspect(engine)
    assert inspector.has_table('baseballStats', schema='default')
    assert not inspector.has_table(
        'no_such_pinot_schema_test', schema='default',
    )


def test_reflection_select_pagination_and_reconnect(engine):
    inspector = inspect(engine)
    assert 'default' in inspector.get_schema_names()
    assert 'baseballStats' in inspector.get_table_names(schema='default')
    metadata = MetaData()
    table = Table('baseballStats', metadata, schema='default',
                  autoload_with=engine)
    columns = inspector.get_columns('baseballStats', schema='default')
    assert set(table.c.keys()) == {column['name'] for column in columns}
    statement = select(table.c.playerID, table.c.yearID).order_by(
        table.c.playerID, table.c.yearID,
    )
    sql = str(statement.compile(engine))
    assert 'default' not in sql
    assert ' AS ' not in sql  # No synthetic schema-disambiguation aliases.
    assert table.schema == 'default'
    assert metadata.tables['default.baseballStats'] is table

    with engine.connect() as connection:
        expected = connection.execute(text(
            'SELECT playerID, yearID FROM baseballStats '
            'ORDER BY playerID, yearID LIMIT 10'
        )).all()
        assert len(expected) == 10
        assert connection.execute(statement.limit(10)).all() == expected
        assert connection.execute(statement.limit(4)).all() == expected[:4]
        assert connection.execute(
            statement.limit(6).offset(4)
        ).all() == expected[4:]
        result = connection.execute(statement.limit(10))
        assert list(result.keys()) == ['playerID', 'yearID']
        assert result.fetchone() == expected[0]
        assert result.fetchmany(3) == expected[1:4]
        assert result.fetchall() == expected[4:]
        assert result.fetchone() is None
        assert all(isinstance(row[0], str) and isinstance(row[1], int)
                   for row in expected)
        assert connection.execute(statement.limit(0)).all() == []
        assert connection.execute(
            select(table.c.playerName).where(table.c.playerName == "O'Brien")
        ).all() == []
        count = connection.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
        assert count > 0
        # Read lifecycle only: Pinot is not transactional.
        connection.rollback()
        connection.invalidate()
        assert connection.execute(
            select(func.count()).select_from(table)
        ).scalar_one() == count

    with engine.begin() as connection:
        assert connection.execute(statement.limit(10)).all() == expected
    old_pool = engine.pool
    engine.dispose()
    assert engine.pool is not old_pool
    with engine.connect() as connection:
        assert connection.execute(statement.limit(10)).all() == expected
