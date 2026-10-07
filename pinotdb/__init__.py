from pinotdb.db import connect, connect_async
from pinotdb.native import NativeQueryMetadata, NativeQueryResult
from pinotdb.exceptions import (
    DataError,
    DatabaseError,
    Error,
    IntegrityError,
    InterfaceError,
    InternalError,
    NotSupportedError,
    OperationalError,
    ProgrammingError,
    Warning,
)


__all__ = [
    "connect",
    "connect_async",
    "NativeQueryMetadata",
    "NativeQueryResult",
    "apilevel",
    "threadsafety",
    "paramstyle",
    "DataError",
    "DatabaseError",
    "Error",
    "IntegrityError",
    "InterfaceError",
    "InternalError",
    "NotSupportedError",
    "OperationalError",
    "ProgrammingError",
    "Warning",
]


apilevel = "2.0"
# Threads may share the module and connections
threadsafety = 2
paramstyle = "pyformat"
