"""Tavily web MCP server: search the live web and read web pages."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from tavily_web_mcp.api import TavilyClient

# Web pages can be very long; return them in chunks of ~5k tokens.
PAGE_CHUNK_CHARS = 20_000

mcp = MCPServer(
    "tavily-web",
    instructions=(
        "Search the live web and read web pages through Tavily. Use search_web to find current sources, then "
        "fetch_url to read a page in full. Cite the URLs you used."
    ),
)

_api: TavilyClient | None = None


def _client() -> TavilyClient:
    # Created on first tool call, so a missing key becomes a message Claude can relay instead of a crash.
    global _api
    if _api is None:
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            raise ToolError("TAVILY_API_KEY is not set. Add it to this server's env in the MCP client config.")
        if not api_key.isascii():  # e.g. a 'ß' typed by Option+S on a Mac; would otherwise crash in the HTTP header
            raise ToolError("TAVILY_API_KEY contains a character that can't be in an API key. Paste the key again.")
        _api = TavilyClient(api_key)
    return _api


class SearchResult(BaseModel):
    title: str
    url: str
    content: str = Field(description="The most relevant excerpts from the page")
    published_date: str | None
    score: float | None = Field(description="Relevance to the query, 0-1")


class SearchResults(BaseModel):
    query: str
    results: list[SearchResult]


class Page(BaseModel):
    url: str
    text: str = Field(description="One chunk of the page's main content as markdown, starting at `offset`")
    offset: int
    total_chars: int
    next_offset: int | None = Field(description="Pass as `offset` to read the next chunk; null when finished")


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@mcp.tool(annotations=READ_ONLY)
async def search_web(
    query: Annotated[str, Field(min_length=1, description="What to search for, phrased like a search query")],
    max_results: Annotated[int, Field(ge=1, le=20, description="Number of results")] = 5,
    topic: Annotated[
        Literal["general", "news", "finance"],
        Field(description="'news' for current events and recent reporting, 'finance' for markets and companies"),
    ] = "general",
    time_range: Annotated[
        Literal["day", "week", "month", "year"] | None,
        Field(description="Only results published or updated within this period"),
    ] = None,
    include_domains: Annotated[
        list[str] | None,
        Field(description="Only search these sites, e.g. ['livelaw.in', 'barandbench.com'] for Indian legal news"),
    ] = None,
) -> SearchResults:
    """Search the live web and return the most relevant pages with excerpts, titles, URLs and publish dates.

    Use for anything current or not covered by the other tools: news, recent legal developments and commentary,
    companies, people, documentation. Call fetch_url on a result's url to read the whole page. When the user
    gives a specific link to read or summarise, use fetch_url on it instead of searching.
    """
    data = await _client().search(
        query,
        max_results=max_results,
        topic=topic,
        time_range=time_range,
        include_domains=include_domains,
        include_published_date=True,
    )
    return SearchResults(
        query=query,
        results=[
            SearchResult(
                title=r.get("title") or "",
                url=r["url"],
                content=r.get("content") or "",
                published_date=r.get("published_date"),
                score=r.get("score"),
            )
            for r in data.get("results") or []
        ],
    )


@mcp.tool(annotations=READ_ONLY)
async def fetch_url(
    url: Annotated[str, Field(description="Full http(s) URL of the page to read")],
    offset: Annotated[int, Field(ge=0, description="Character offset to read from; use next_offset")] = 0,
) -> Page:
    """Read the page at a given URL and return its text as markdown (site menus may remain at the top).

    Use whenever the user gives a link to read, summarise or check, and to read a search_web result in full.
    Long pages come in 20,000-character chunks: when next_offset is not null and you need more, call again with
    offset=next_offset.
    """
    # ponytail: re-extracts the page for every chunk; cache by url if long pages get read often.
    result = await _client().extract(url)
    text = result.get("raw_content") or ""
    end = offset + PAGE_CHUNK_CHARS
    return Page(
        url=result.get("url", url),
        text=text[offset:end],
        offset=offset,
        total_chars=len(text),
        next_offset=end if end < len(text) else None,
    )


def main() -> None:
    mcp.run()  # stdio: the client (e.g. Claude Desktop) launches this process and talks over stdin/stdout
