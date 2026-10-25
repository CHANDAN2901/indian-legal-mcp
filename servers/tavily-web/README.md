# tavily-web-mcp

An MCP server for live web search and reading web pages through the [Tavily API](https://docs.tavily.com/).

## Tools

| Tool | What it does |
|---|---|
| `search_web(query, max_results?, topic?, time_range?, include_domains?)` | Live web search. Returns each result's title, URL, the most relevant excerpts, publish date and a relevance score. `topic="news"` targets current reporting, and `include_domains` limits results to chosen sites. |
| `fetch_url(url, offset?)` | Reads one page as markdown in 20,000-character chunks (`next_offset` gives the next one). Scripts and styling are removed, but the site's menus can still appear at the top. |

Tavily fetches the pages on its own servers, so `fetch_url` never connects from your machine to the URL.

## Setup

1. Get an API key at [app.tavily.com](https://app.tavily.com). The free plan includes 1,000 credits a month.
2. Add the server to Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`):

   ```json
   {
     "mcpServers": {
       "tavily-web": {
         "command": "uv",
         "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/servers/tavily-web", "tavily-web-mcp"],
         "env": { "TAVILY_API_KEY": "tvly-..." }
       }
     }
   }
   ```

3. Restart Claude Desktop.

## Cost

Each `search_web` call costs 1 credit (it uses `basic` search depth). Each `fetch_url` call costs about 0.2 credits,
because Tavily bills 1 credit per 5 pages read. Reading every chunk of a long page counts as reading the page again.
See [credits](https://docs.tavily.com/documentation/api-credits).
