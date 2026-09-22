"""Synthetic reflection schemas must not become Pinot SQL qualifiers."""
import pytest
from sqlalchemy import Column, Integer, MetaData, Table, select
from sqlalchemy.schema import CreateTable

from pinotdb import sqlalchemy as ps


DIALECTS = [
    ps.PinotHTTPDialect, ps.PinotHTTPSDialect,
    ps.PinotHTTPAsyncDialect, ps.PinotHTTPSAsyncDialect,
    ps.PinotMultiStageDialect, ps.PinotHTTPSMultiStageDialect,
    ps.PinotMultiStageAsyncDialect, ps.PinotHTTPSMultiStageAsyncDialect,
]


def events(schema):
    return Table(
        'EventData', MetaData(), Column('event_count', Integer), schema=schema,
    )


@pytest.mark.parametrize('dialect_cls', DIALECTS)
@pytest.mark.parametrize('schema', [None, 'default', 'analytics'])
def test_select_omits_schema_without_changing_metadata(dialect_cls, schema):
    dialect = dialect_cls(paramstyle="pyformat")
    table = events(schema)
    statement = (select(table.c.event_count)
                 .where(table.c.event_count > 7)
                 .order_by(table.c.event_count).limit(3).offset(2))
    compiled = statement.compile(dialect=dialect)
    assert str(compiled) == (
        'SELECT "EventData".event_count \nFROM "EventData" \n'
        'WHERE "EventData".event_count > %(event_count_1)s '
        'ORDER BY "EventData".event_count\n'
        ' LIMIT %(param_1)s OFFSET %(param_2)s'
    )
    assert compiled.params == {'event_count_1': 7, 'param_1': 3, 'param_2': 2}
    assert table.schema == schema
    assert table.c.event_count.table is table
    assert table.metadata.tables[table.key] is table
    assert 'default' not in str(CreateTable(table).compile(dialect=dialect))


@pytest.mark.parametrize('shape', ['alias', 'subquery', 'join'])
def test_explicit_aliases_and_subqueries_are_preserved(shape):
    def statement(schema):
        table = events(schema)
        alias = table.alias('e')
        if shape == 'alias':
            return select(alias.c.event_count)
        if shape == 'subquery':
            subquery = select(table.c.event_count).subquery('s')
            return select(subquery.c.event_count)
        return select(table.c.event_count, alias.c.event_count).select_from(
            table.join(alias, table.c.event_count == alias.c.event_count)
        )

    dialect = ps.PinotHTTPDialect()
    sql = str(statement('default').compile(dialect=dialect))
    assert sql == str(statement(None).compile(dialect=dialect))
    assert ' AS ' in sql
    assert 'default' not in sql


@pytest.mark.parametrize('schema', [None, 'default'])
@pytest.mark.parametrize('mapping', [
    {'default': 'other'}, {'default': None}, {None: 'other'},
])
def test_schema_translation_cannot_reintroduce_qualifiers(schema, mapping):
    table = events(schema)
    sql = str(select(table.c.event_count).compile(
        dialect=ps.PinotHTTPDialect(), schema_translate_map=mapping,
        render_schema_translate=True,
    ))
    assert sql == 'SELECT "EventData".event_count \nFROM "EventData"'
    assert table.schema == schema


def test_explicit_preparer_opt_out_retains_schema_and_translation():
    dialect = ps.PinotHTTPDialect()
    preparer = ps.PinotIdentifierPareparer(dialect, omit_schema=False)
    table = events('default')
    assert preparer.schema_for_object(table) == 'default'
    translated = preparer._with_schema_translate({'default': 'other'})
    assert translated.schema_for_object(table) == '__[SCHEMA_default]'
