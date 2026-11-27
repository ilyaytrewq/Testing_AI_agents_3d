"""Logging of exceptions without leaking stored data.

Database error messages can quote row contents ("Key (question)=(...) already exists"),
so for them only the class, SQLSTATE and constraint name are logged, never the text or
the traceback (which repeats the text).
"""

import logging

from asyncpg import PostgresError
from sqlalchemy.exc import DBAPIError


def _database_fields(error: BaseException) -> str | None:
    if isinstance(error, DBAPIError):
        candidates: list[object] = [error.orig, getattr(error.orig, "__cause__", None)]
    elif isinstance(error, PostgresError):
        candidates = [error]
    else:
        return None
    sqlstate = constraint = None
    for candidate in candidates:
        if candidate is None:
            continue
        sqlstate = (
            sqlstate or getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        )
        constraint = constraint or getattr(candidate, "constraint_name", None)
    return f"{type(error).__name__} sqlstate={sqlstate or 'unknown'} constraint={constraint or '-'}"


def log_exception(
    logger: logging.Logger, message: str, error: BaseException, *args: object
) -> None:
    """Log `message % (*args, description)` at ERROR; a traceback only for non-database errors."""
    fields = _database_fields(error)
    if fields is not None:
        logger.error(message, *args, fields)
    else:
        logger.error(message, *args, type(error).__name__, exc_info=error)
