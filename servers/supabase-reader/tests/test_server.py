"""Drives the tools through a real in-process MCP client against a real Postgres.

Point TEST_DATABASE_URL at a throwaway database (never your Supabase project): the tests create and drop
`mcp_test_*` tables there. For example:
    docker run -d -p 54329:5432 -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17
    TEST_DATABASE_URL=postgresql://postgres@localhost:54329/postgres uv run pytest
"""

import os

import psycopg
import pytest
from mcp import Client

from supabase_reader_mcp import server
from supabase_reader_mcp.db import DatabaseError, read_only

pytestmark = pytest.mark.anyio
TEST_DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to a throwaway Postgres")

SETUP = """
DROP TABLE IF EXISTS mcp_test_orders, mcp_test_customers;
CREATE TABLE mcp_test_customers (
    id int PRIMARY KEY, name text, email text, city text, notes jsonb, deleted_at timestamptz
);
CREATE TABLE mcp_test_orders (
    id int PRIMARY KEY, customer_id int REFERENCES mcp_test_customers, amount numeric(10, 2), status text
);
INSERT INTO mcp_test_customers VALUES
    (1, 'Alice Sharma', 'alice@example.com', 'Delhi', '{"vip": true}', NULL),
    (2, 'Bob Iyer', 'bob@example.com', 'Chennai', NULL, '2026-01-01'),
    (3, 'Carol 100% Real', 'carol@example.com', 'Delhi', NULL, NULL);
INSERT INTO mcp_test_orders VALUES (10, 1, 499.00, 'paid'), (11, 1, 99.50, 'refunded'), (12, 3, 1200.00, 'paid');
"""


@pytest.fixture
def db(monkeypatch):
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute(SETUP)
    monkeypatch.setenv("SUPABASE_DB_URL", TEST_DB)
    yield
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP TABLE mcp_test_orders, mcp_test_customers")


async def call(tool: str, **arguments):
    async with Client(server.mcp) as client:
        return await client.call_tool(tool, arguments)


async def test_missing_connection_string_is_reported(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    result = await call("list_tables")
    assert result.is_error
    assert "SUPABASE_DB_URL is not set" in result.content[0].text


@needs_db
async def test_list_tables_shows_columns_and_types(db):
    tables = {t["name"]: t["columns"] for t in (await call("list_tables")).structured_content["tables"]}
    assert tables["mcp_test_orders"] == {
        "id": "integer",
        "customer_id": "integer",
        "amount": "numeric",
        "status": "text",
    }


@needs_db
async def test_query_table_filters_sorts_and_selects(db):
    paid = await call(
        "query_table",
        table="mcp_test_orders",
        filters={"status": "paid"},
        columns=["id", "amount"],
        order_by="amount",
        descending=True,
    )
    assert paid.structured_content["rows"] == [{"id": 12, "amount": "1200.00"}, {"id": 10, "amount": "499.00"}]

    active_delhi = await call(
        "query_table", table="mcp_test_customers", filters={"city": "Delhi", "deleted_at": None}, order_by="id"
    )
    rows = active_delhi.structured_content["rows"]
    assert [r["id"] for r in rows] == [1, 3]
    assert rows[0]["notes"] == '{"vip": true}'  # jsonb comes back as compact JSON text


@needs_db
async def test_search_records_matches_text_anywhere_and_treats_wildcards_literally(db):
    alice = (await call("search_records", query="ALICE")).structured_content["matches"]
    assert [r["id"] for r in alice["mcp_test_customers"]] == [1]
    assert "mcp_test_orders" not in alice

    percent = (await call("search_records", query="%")).structured_content["matches"]
    assert [r["name"] for r in percent["mcp_test_customers"]] == ["Carol 100% Real"]  # not every row


@needs_db
async def test_unknown_names_are_rejected_before_any_sql_runs(db):
    injection = await call("query_table", table="mcp_test_orders; DROP TABLE mcp_test_customers")
    bad_column = await call("query_table", table="mcp_test_orders", filters={"status = 'paid' OR 1=1 --": "x"})

    assert injection.is_error and "No table" in injection.content[0].text
    assert bad_column.is_error and "No column" in bad_column.content[0].text
    assert (await call("query_table", table="mcp_test_customers")).structured_content["count"] == 3


@needs_db
async def test_connection_refuses_writes(db):
    with pytest.raises(DatabaseError, match="read-only transaction"):
        async with read_only(TEST_DB) as conn:
            await conn.execute("DELETE FROM mcp_test_orders")
