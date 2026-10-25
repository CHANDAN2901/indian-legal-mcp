# indian-legal-mcp

Three [MCP](https://modelcontextprotocol.io) servers that give Claude, or any MCP client, three sources of
information: **Indian case law**, **your own database**, and **the live web**. The repo also includes the eval used
to check that the model picks the right tool among them.

<!-- Demo video: on GitHub, edit this README and drag the .mp4 here to embed it. -->

One question can use all three servers:

> *"For Sneha Kulkarni's open matter, read the court's order in the precedent it relies on, then search recent news
> on the DPDP Act and tell me whether it strengthens her case against a private employer."*

| Step | Server | Tool call | What it gets |
|---|---|---|---|
| 1 | supabase-reader | `search_records("Sneha")`, then `query_table("legal_matters", ...)` | Her open matter, which relies on case `91938676` |
| 2 | indiankanoon | `get_judgment(91938676, offset=-20000)` | The *Order of the Court* in Puttaswamy (2017): privacy is a fundamental right under Article 21 |
| 3 | tavily-web | `search_web(..., topic="news")`, then `fetch_url(...)` | 2026 commentary on employers as "Data Fiduciaries" under the DPDP Act |

Claude then answers from all three sources and raises the key legal gap itself: Puttaswamy binds the State, while
the DPDP Act binds a private employer.

## Servers

| Server | Tools | What it needs |
|---|---|---|
| [`indiankanoon-mcp`](servers/indiankanoon) | `search_cases`, `get_judgment` | An [IndianKanoon API](https://api.indiankanoon.org/) token (new accounts get Rs 500 of credit) |
| [`supabase-reader-mcp`](servers/supabase-reader) | `list_tables`, `query_table`, `search_records` | A Supabase (or any Postgres) connection string |
| [`tavily-web-mcp`](servers/tavily-web) | `search_web`, `fetch_url` | A [Tavily](https://app.tavily.com) API key (1,000 free credits a month) |

Each server is its own Python package, and you can run any one of them by itself.

## Quickstart (Claude Desktop)

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Claude Desktop](https://claude.ai/download).

```bash
git clone https://github.com/CHANDAN2901/indian-legal-mcp.git
cd indian-legal-mcp
uv sync --all-packages
```

Add the servers you want to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows). Replace `/ABSOLUTE/PATH` with the folder you cloned into:

```json
{
  "mcpServers": {
    "indiankanoon": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/indian-legal-mcp/servers/indiankanoon", "indiankanoon-mcp"],
      "env": { "INDIANKANOON_API_TOKEN": "your-token" }
    },
    "supabase-reader": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/indian-legal-mcp/servers/supabase-reader", "supabase-reader-mcp"],
      "env": { "SUPABASE_DB_URL": "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres" }
    },
    "tavily-web": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/indian-legal-mcp/servers/tavily-web", "tavily-web-mcp"],
      "env": { "TAVILY_API_KEY": "tvly-..." }
    }
  }
}
```

Then fully quit Claude Desktop and reopen it. If it can't find `uv`, set `command` to the full path that `which uv`
prints.

Want the demo data? Paste [`servers/supabase-reader/demo_seed.sql`](servers/supabase-reader/demo_seed.sql) into the
Supabase SQL Editor. It creates a small, fictional law-practice tracker whose matters link to real IndianKanoon case
IDs.

## Does the model pick the right tool?

[`evals/tool_selection.py`](evals/tool_selection.py) sends 30 questions to a model, together with the servers' real
tool definitions, and checks which tool the model calls first. The questions include deliberate overlaps: a
judgment link versus a web page, case law versus legal news, and questions that need no tool at all.

| Model | Before tuning | After tuning |
|---|---|---|
| gpt-5.4-mini (3 runs) | 89/90, 98.9% | **90/90, 100%** |
| gpt-4.1-mini (stress test) | 28/30, 93% | 28/30 and 29/30, 93% / 97% |

Every miss before tuning involved a **link**. For example, the model scraped an `indiankanoon.org/doc/<id>/` page
as a generic web page instead of calling `get_judgment` with the ID from the link. Two description changes fixed it.
An OpenAI model stands in for Claude in the eval, so the 4 hardest questions were also checked by hand in Claude
Desktop. Every run is logged in [`evals/history.jsonl`](evals/history.jsonl).

## Design notes

- **Long judgments, read efficiently.** Puttaswamy is 848,793 characters long, and the court's order sits at the
  end. `get_judgment` returns 20,000-character chunks, and `offset=-20000` jumps straight to the final order: one
  call instead of about 43.
- **Read-only, enforced by Postgres.** Every database tool call runs in a `READ ONLY` transaction. Table and column
  names are checked against the real schema, and values are sent as query parameters. Only the `public` schema is
  visible, so Supabase's `auth` tables stay out of reach. Tests cover SQL injection attempts and blocked writes.
- **Failures Claude can explain.** Expected failures come back as readable messages, such as an invalid token, a
  plan limit, an unknown court or an unreadable page, instead of the MCP SDK's generic "Error executing tool".
- **The API docs aren't always right.** IndianKanoon's documentation says a judgment's citations come back as
  `citeList`. The live API sends `cites`. Live tests caught it, and the code follows the live API.
- **Built on MCP Python SDK v2.** In v2, `FastMCP` was renamed to `MCPServer` (`from mcp.server import MCPServer`),
  so v1 tutorials need that change.

This is a research aid, not legal advice. Check every citation against the source.

## Repository layout

```
├── pyproject.toml          # uv workspace: one lockfile, shared dev tools (pytest, ruff)
├── evals/                  # tool-selection eval + run history
└── servers/
    ├── indiankanoon/       # api.py (HTTP client) + server.py (MCP tools) + tests
    ├── supabase-reader/    # db.py (read-only Postgres) + server.py + demo_seed.sql + tests
    └── tavily-web/         # api.py (HTTP client) + server.py + tests
```

In each server, `api.py` or `db.py` holds the data access with no MCP tool definitions, so other code can reuse it.
`server.py` defines only the tools the model sees.

## Development

```bash
uv sync --all-packages
uv run pytest                    # APIs are mocked; database tests skip without TEST_DATABASE_URL
uv run ruff check . && uv run ruff format .

# Database tests need a throwaway Postgres. They create and drop mcp_test_* tables.
docker run -d -p 54329:5432 -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17
TEST_DATABASE_URL=postgresql://postgres@localhost:54329/postgres uv run pytest

# Tool-selection eval: copy .env.example to .env and add an OpenAI key.
uv run --env-file .env python evals/tool_selection.py

# Try one server in the MCP Inspector (needs Node.js):
npx @modelcontextprotocol/inspector uv run --directory servers/indiankanoon indiankanoon-mcp
```

## Roadmap

- A WebMCP manifest, so browser-based agents can find the IndianKanoon tools
- API-key authentication with per-key usage limits
- A `research_legal_question` meta-server that chains all three servers
- Timeouts, rate limiting and retries
- Publishing each server to PyPI (`pip install indiankanoon-mcp`)

## License

[MIT](LICENSE)
