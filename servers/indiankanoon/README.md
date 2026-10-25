# indiankanoon-mcp

An MCP server for searching and reading Indian court judgments (Supreme Court, High Courts, tribunals) through the
[IndianKanoon API](https://api.indiankanoon.org/documentation/).

## Tools

| Tool | What it does |
|---|---|
| `search_cases(query, court?, year?, page?)` | Full-text search. Returns `case_id`, title, court, date, a matching snippet, and citation counts. 10 results per page. |
| `get_judgment(case_id, offset?)` | Full judgment text in 20,000-character chunks (`next_offset` gives the next one), plus the top cases it cites and that cite it. A negative `offset` counts from the end: `-20000` returns the final order in one call. |

`query` supports quoted phrases and the operators `ANDD`, `ORR`, `NOTT`. `court` accepts IndianKanoon `doctypes`
values such as `supremecourt`, `highcourts`, `delhi`, `bombay`, `tribunals`, or `itat`. Combine them with commas.

## Setup

1. Create an account at [api.indiankanoon.org](https://api.indiankanoon.org/) and generate an API token. New accounts
   get Rs 500 of free credit. Non-commercial use can apply for Rs 10,000 a month.
2. Add the server to your MCP client. For Claude Desktop, edit
   `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "indiankanoon": {
         "command": "uv",
         "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/servers/indiankanoon", "indiankanoon-mcp"],
         "env": { "INDIANKANOON_API_TOKEN": "your-token" }
       }
     }
   }
   ```

   If Claude Desktop can't find `uv`, set `command` to the full path that `which uv` prints.
3. Restart Claude Desktop.

## Cost

Each `search_cases` call costs Rs 0.50. Each `get_judgment` call costs Rs 0.20, including every additional chunk,
because each chunk fetches the document again. See [pricing](https://api.indiankanoon.org/pricing/).
