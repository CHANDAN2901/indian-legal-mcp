"""Read-only access to the public schema of a Supabase (or any Postgres) database."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from mcp.server.mcpserver.exceptions import ToolError
from psycopg import sql
from psycopg.rows import dict_row

# Supabase keeps app tables in `public`; its auth/storage schemas hold internals like password hashes.
SCHEMA = "public"
TEXT_TYPES = frozenset({"text", "character varying", "character"})
# Long text, jsonb and pgvector columns would otherwise flood the model's context.
MAX_CELL_CHARS = 500

Schema = dict[str, dict[str, str]]  # table -> column -> data type
Row = dict[str, Any]


class DatabaseError(ToolError):
    """A database failure. Subclasses ToolError so the MCP client shows the message to the model."""


@asynccontextmanager
async def read_only(url: str) -> AsyncIterator[psycopg.AsyncConnection]:
    """One connection, one read-only transaction: Postgres itself rejects any write."""
    try:
        # prepare_threshold=None: Supabase's transaction pooler (port 6543) can't use prepared statements.
        async with await psycopg.AsyncConnection.connect(
            url, row_factory=dict_row, prepare_threshold=None, connect_timeout=10
        ) as conn:
            async with conn.transaction():
                await conn.execute("SET TRANSACTION READ ONLY")
                await conn.execute("SET LOCAL statement_timeout = '10s'")
                yield conn
    except psycopg.Error as e:
        raise DatabaseError(f"Database error: {e}".strip()) from e


async def load_schema(conn: psycopg.AsyncConnection) -> Schema:
    cur = await conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = %s ORDER BY table_name, ordinal_position",
        (SCHEMA,),
    )
    schema: Schema = {}
    for row in await cur.fetchall():
        schema.setdefault(row["table_name"], {})[row["column_name"]] = row["data_type"]
    return schema


def check_names(schema: Schema, table: str, columns: Iterable[str] = ()) -> None:
    """Names come from the model: reject unknown ones with a message listing the real ones."""
    if table not in schema:
        raise DatabaseError(f"No table {table!r} in schema {SCHEMA!r}. Tables: {', '.join(schema) or '(none)'}")
    unknown = [c for c in columns if c not in schema[table]]
    if unknown:
        raise DatabaseError(f"No column {unknown} in {table!r}. Columns: {', '.join(schema[table])}")


def cell(value: Any) -> Any:
    """Make one column value JSON-safe and short."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, dict | list):
        text = json.dumps(value, default=str)
    else:
        text = str(value)  # str, Decimal, datetime, UUID, pgvector, ...
    return text if len(text) <= MAX_CELL_CHARS else f"{text[:MAX_CELL_CHARS]}… [{len(text)} chars]"


def clean(rows: list[Row]) -> list[Row]:
    return [{k: cell(v) for k, v in row.items()} for row in rows]


async def select(
    conn: psycopg.AsyncConnection,
    table: str,
    filters: dict[str, Any],
    columns: list[str] | None,
    order_by: str | None,
    descending: bool,
    limit: int,
) -> list[Row]:
    query = sql.SQL("SELECT {} FROM {}").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)) if columns else sql.SQL("*"),
        sql.Identifier(SCHEMA, table),
    )
    conditions = [
        sql.SQL("{} IS NULL" if value is None else "{} = %s").format(sql.Identifier(column))
        for column, value in filters.items()
    ]
    if conditions:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
    if order_by:
        query += sql.SQL(" ORDER BY {} " + ("DESC" if descending else "ASC")).format(sql.Identifier(order_by))
    query += sql.SQL(" LIMIT %s")
    params = [value for value in filters.values() if value is not None]
    cur = await conn.execute(query, [*params, limit])
    return clean(await cur.fetchall())


async def search(conn: psycopg.AsyncConnection, schema: Schema, text: str, limit: int) -> dict[str, list[Row]]:
    """Case-insensitive substring match over every text column of every table in `schema`."""
    # ponytail: ILIKE is a sequential scan per table; switch to tsvector + GIN indexes if tables get large.
    pattern = "%" + re.sub(r"([\\%_])", r"\\\1", text) + "%"  # treat the user's % and _ literally
    matches: dict[str, list[Row]] = {}
    for table, columns in schema.items():
        text_columns = [c for c, data_type in columns.items() if data_type in TEXT_TYPES]
        if not text_columns:
            continue
        where = sql.SQL(" OR ").join(sql.SQL("{} ILIKE %(pattern)s").format(sql.Identifier(c)) for c in text_columns)
        query = sql.SQL("SELECT * FROM {} WHERE {} LIMIT %(limit)s").format(sql.Identifier(SCHEMA, table), where)
        cur = await conn.execute(query, {"pattern": pattern, "limit": limit})
        if rows := await cur.fetchall():
            matches[table] = clean(rows)
    return matches
