"""Supabase reader MCP server: explore and query a Postgres database, read-only."""

from __future__ import annotations

import os
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from supabase_reader_mcp.db import check_names, load_schema, read_only, search, select

mcp = MCPServer(
    "supabase-reader",
    instructions=(
        "Read-only access to a Supabase Postgres database (public schema). Start with list_tables to learn the "
        "exact table and column names, then use query_table for structured lookups or search_records to find text "
        "anywhere in the database."
    ),
)


def _db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise ToolError("SUPABASE_DB_URL is not set. Add the Postgres connection string to this server's env.")
    return url


class Table(BaseModel):
    name: str
    columns: dict[str, str] = Field(description="Column name -> Postgres type")


class Tables(BaseModel):
    tables: list[Table]


class Rows(BaseModel):
    table: str
    rows: list[dict[str, Any]]
    count: int = Field(description="Number of rows returned; equals `limit` when more rows may exist")


class SearchResults(BaseModel):
    query: str
    matches: dict[str, list[dict[str, Any]]] = Field(description="Table name -> matching rows")


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


@mcp.tool(annotations=READ_ONLY)
async def list_tables() -> Tables:
    """List every table and view in the Supabase database with its columns and their Postgres types.

    Call this first when you don't yet know the database's tables: query_table and search_records need exact
    table and column names.
    """
    async with read_only(_db_url()) as conn:
        schema = await load_schema(conn)
    return Tables(tables=[Table(name=name, columns=columns) for name, columns in schema.items()])


@mcp.tool(annotations=READ_ONLY)
async def query_table(
    table: Annotated[str, Field(description="Exact table name from list_tables")],
    filters: Annotated[
        dict[str, str | int | float | bool | None] | None,
        Field(
            description="Exact-match conditions, all of which must hold: {column: value}. "
            "null matches empty (IS NULL) values. Example: {'status': 'paid', 'customer_id': 42}"
        ),
    ] = None,
    columns: Annotated[list[str] | None, Field(description="Columns to return; omit for all columns")] = None,
    order_by: Annotated[str | None, Field(description="Column to sort by")] = None,
    descending: Annotated[bool, Field(description="Sort newest/largest first")] = False,
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum rows to return")] = 20,
) -> Rows:
    """Read rows from one table in the Supabase database, optionally filtered by exact values, sorted and limited.

    Use for structured lookups such as "the 10 most recent orders" (order_by=created_at, descending=true, limit=10)
    or "the user with email x" (filters={"email": "x"}). Values longer than 500 characters are cut.
    """
    filters = filters or {}
    async with read_only(_db_url()) as conn:
        check_names(await load_schema(conn), table, [*filters, *(columns or []), *([order_by] if order_by else [])])
        rows = await select(conn, table, filters, columns, order_by, descending, limit)
    return Rows(table=table, rows=rows, count=len(rows))


@mcp.tool(annotations=READ_ONLY)
async def search_records(
    query: Annotated[str, Field(min_length=1, description="Text to look for, case-insensitive")],
    table: Annotated[str | None, Field(description="Only search this table; omit to search every table")] = None,
    limit_per_table: Annotated[int, Field(ge=1, le=50, description="Maximum matching rows per table")] = 5,
) -> SearchResults:
    """Find rows anywhere in the Supabase database whose text columns contain the given text (case-insensitive).

    Use when you know a value (a name, email, keyword) but not which table or column holds it. Results are grouped
    by table; use query_table afterwards for exact, sorted lookups.
    """
    async with read_only(_db_url()) as conn:
        schema = await load_schema(conn)
        if table:
            check_names(schema, table)
            schema = {table: schema[table]}
        matches = await search(conn, schema, query, limit_per_table)
    return SearchResults(query=query, matches=matches)


def main() -> None:
    mcp.run()  # stdio: the client (e.g. Claude Desktop) launches this process and talks over stdin/stdout
