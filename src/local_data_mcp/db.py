"""Read-only access layer over a local SQLite database."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Statements the ad-hoc query tool may start with. Everything else is rejected
# before it reaches SQLite; the authorizer below is the real enforcement.
_READ_PREFIX = re.compile(r"^\s*(select|with|explain)\b", re.IGNORECASE)

# SQLite authorizer action codes that only read data.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


class QueryError(ValueError):
    """Raised for queries that are invalid or not allowed."""


def _authorizer(action: int, *_: Any) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


class Database:
    """Opens short-lived, read-only connections to a SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"Database not found at {self.path}. Run `local-data-mcp --seed` to create a sample one."
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # mode=ro makes the file itself read-only for this connection.
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def fetch_all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def fetch_one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.fetch_all(sql, params)
        return rows[0] if rows else None

    def table_names(self) -> list[str]:
        rows = self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r["name"] for r in rows]

    def require_table(self, table: str) -> str:
        """Validate a table name against the real schema (never interpolate raw input)."""
        if table not in self.table_names():
            raise QueryError(f"Unknown table {table!r}. Available: {', '.join(self.table_names())}")
        return table

    def run_readonly(self, sql: str, limit: int) -> tuple[list[str], list[dict[str, Any]], bool]:
        """Run an arbitrary read-only statement, returning (columns, rows, truncated)."""
        if not _READ_PREFIX.match(sql):
            raise QueryError("Only SELECT, WITH or EXPLAIN statements are allowed.")
        if ";" in sql.strip().rstrip(";"):
            raise QueryError("Only a single statement is allowed.")
        with self.connect() as conn:
            conn.set_authorizer(_authorizer)
            try:
                cursor = conn.execute(sql)
                rows = cursor.fetchmany(limit + 1)
            except sqlite3.Error as exc:
                raise QueryError(f"SQLite error: {exc}") from exc
            columns = [d[0] for d in cursor.description or ()]
        truncated = len(rows) > limit
        return columns, [dict(r) for r in rows[:limit]], truncated
