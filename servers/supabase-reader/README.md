# supabase-reader-mcp

A read-only MCP server for exploring and querying a Supabase database. It also works with any Postgres database,
because it connects with a standard Postgres connection string.

## Tools

| Tool | What it does |
|---|---|
| `list_tables()` | Every table and view in the `public` schema, with column names and Postgres types. |
| `query_table(table, filters?, columns?, order_by?, descending?, limit?)` | Rows from one table. Filters are exact matches (`null` matches `IS NULL`). Returns up to 100 rows. |
| `search_records(query, table?, limit_per_table?)` | Case-insensitive text search across every text column of every table. Results are grouped by table. |

## Safety

- **Read-only, enforced by Postgres.** Every tool call runs inside a `READ ONLY` transaction, so the database
  rejects any write, even if a bug let one through.
- **No raw SQL from the model.** Table and column names are checked against the real schema and quoted as
  identifiers. Values are always sent as query parameters.
- **Bounded.** Queries time out after 10 seconds, results are limited to 100 rows, and values longer than 500
  characters are cut. Long text, `jsonb` and embedding columns would otherwise fill the model's context.
- **`public` schema only.** Supabase's `auth` and `storage` schemas hold internals such as password hashes.

The server reads everything the connecting role can read. The default `postgres` role owns your tables, so
row-level security policies don't limit it. To narrow access, create a role with `SELECT` on only the tables you
want to expose, and use that role's connection string.

## Setup

1. In the Supabase dashboard, open your project, click **Connect**, and copy the **Session pooler** connection
   string. It looks like this:

   ```
   postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```

   Use the pooler string rather than the "Direct connection" one. The direct host (`db.<ref>.supabase.co`) only
   works over IPv6, which many home networks don't have. If your password contains characters such as `@`, `#` or
   `/`, URL-encode them (for example `@` becomes `%40`).
2. Add the server to Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

   ```json
   {
     "mcpServers": {
       "supabase-reader": {
         "command": "uv",
         "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/servers/supabase-reader", "supabase-reader-mcp"],
         "env": { "SUPABASE_DB_URL": "postgresql://..." }
       }
     }
   }
   ```

3. Restart Claude Desktop.

No tables yet? [`demo_seed.sql`](demo_seed.sql) creates a small law-practice tracker (clients, legal matters,
hearings). Its matters link to real IndianKanoon case IDs, so Claude can use this server and `indiankanoon-mcp`
together. Paste it into the Supabase SQL Editor to load it.

## Tests

The tests run against a real Postgres. Point `TEST_DATABASE_URL` at a **throwaway** database, never your Supabase
project, because the tests create and drop `mcp_test_*` tables there. Without the variable, those tests are skipped.

```bash
docker run -d -p 54329:5432 -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17
TEST_DATABASE_URL=postgresql://postgres@localhost:54329/postgres uv run pytest
```
