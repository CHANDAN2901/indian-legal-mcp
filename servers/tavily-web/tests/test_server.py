"""Drives both tools through a real in-process MCP client, with the Tavily API mocked."""

import json
from types import SimpleNamespace

import httpx2
import pytest
from mcp import Client

from tavily_web_mcp import server
from tavily_web_mcp.api import TavilyClient

pytestmark = pytest.mark.anyio


@pytest.fixture
def api(monkeypatch):
    """Point the server at a fake API: set `responses` by URL path, inspect `requests` afterwards."""
    fake = SimpleNamespace(requests=[], responses={})

    def handler(request: httpx2.Request) -> httpx2.Response:
        fake.requests.append(request)
        return fake.responses[request.url.path]

    monkeypatch.setattr(server, "_api", TavilyClient("tvly-test", transport=httpx2.MockTransport(handler)))
    return fake


async def call(tool: str, **arguments):
    async with Client(server.mcp) as client:
        return await client.call_tool(tool, arguments)


async def test_search_web_sends_only_given_options_and_parses_results(api):
    api.responses["/search"] = httpx2.Response(
        200,
        json={
            "query": "dpdp rules",
            "results": [
                {
                    "title": "DPDP Rules notified",
                    "url": "https://www.livelaw.in/dpdp",
                    "content": "The Ministry notified the rules...",
                    "score": 0.91,
                    "published_date": "2026-10-20",
                }
            ],
        },
    )

    result = await call("search_web", query="dpdp rules", topic="news", include_domains=["livelaw.in"])

    request = api.requests[0]
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer tvly-test"
    assert json.loads(request.content) == {
        "query": "dpdp rules",
        "max_results": 5,
        "topic": "news",
        "include_domains": ["livelaw.in"],
        "include_published_date": True,
    }  # time_range left out, so Tavily uses its default
    assert result.structured_content["results"][0]["url"] == "https://www.livelaw.in/dpdp"


async def test_fetch_url_chunks_long_pages(api):
    page = "# Title\n" + "y" * server.PAGE_CHUNK_CHARS
    api.responses["/extract"] = httpx2.Response(200, json={"results": [{"url": "https://a.in", "raw_content": page}]})

    first = (await call("fetch_url", url="https://a.in")).structured_content
    rest = (await call("fetch_url", url="https://a.in", offset=first["next_offset"])).structured_content

    assert json.loads(api.requests[0].content) == {"urls": ["https://a.in"], "format": "markdown"}
    assert first["next_offset"] == server.PAGE_CHUNK_CHARS
    assert first["text"] + rest["text"] == page
    assert rest["next_offset"] is None


async def test_errors_reach_the_model_as_readable_messages(api, monkeypatch):
    api.responses["/search"] = httpx2.Response(432, json={"detail": {"error": "This request exceeds your plan"}})
    api.responses["/extract"] = httpx2.Response(  # HTTP 200, but the page itself failed
        200, json={"results": [], "failed_results": [{"url": "https://x.in", "error": "Failed to retrieve content"}]}
    )

    plan_limit = await call("search_web", query="x")
    unreadable = await call("fetch_url", url="https://x.in")
    monkeypatch.setattr(server, "_api", None)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    no_key = await call("search_web", query="x")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-dev-abcß")  # 'ß' from pressing Option+S instead of Cmd+S
    stray_char = await call("search_web", query="x")

    for result, message in [
        (plan_limit, "Tavily API error 432: This request exceeds your plan"),
        (unreadable, "Could not read https://x.in: Failed to retrieve content"),
        (no_key, "TAVILY_API_KEY is not set"),
        (stray_char, "contains a character that can't be in an API key"),
    ]:
        assert result.is_error
        assert message in result.content[0].text
