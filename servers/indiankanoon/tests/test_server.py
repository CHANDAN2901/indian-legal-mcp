"""Drives both tools through a real in-process MCP client, with the IndianKanoon API mocked."""

from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx2
import pytest
from mcp import Client

from indiankanoon_mcp import server
from indiankanoon_mcp.api import IndianKanoonClient

pytestmark = pytest.mark.anyio

SEARCH_RESPONSE = {
    "found": "1 - 10 of 2345",
    "docs": [
        {
            "tid": 91938676,
            "title": "Justice K.S.Puttaswamy (Retd) vs Union Of India",
            "headline": "the <b>right to privacy</b> is\n\nprotected as an intrinsic part",
            "docsource": "Supreme Court of India",
            "publishdate": "2017-08-24",
            "numcites": 120,
            "numcitedby": 900,
            "citation": "AIR 2017 SUPREME COURT 4161",
            "author": "D Y Chandrachud",
        }
    ],
}


@pytest.fixture
def api(monkeypatch):
    """Point the server at a fake API: set `responses` by URL path, inspect `requests` afterwards."""
    fake = SimpleNamespace(requests=[], responses={})

    def handler(request: httpx2.Request) -> httpx2.Response:
        fake.requests.append(request)
        return fake.responses[request.url.path]

    monkeypatch.setattr(server, "_api", IndianKanoonClient("test-token", transport=httpx2.MockTransport(handler)))
    return fake


async def test_search_cases_sends_filters_and_parses_results(api):
    api.responses["/search/"] = httpx2.Response(200, json=SEARCH_RESPONSE)

    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "search_cases", {"query": '"right to privacy"', "court": "supremecourt", "year": 2017}
        )

    assert not result.is_error, result.content
    request = api.requests[0]
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Token test-token"
    assert parse_qs(request.url.query.decode())["formInput"] == [
        '"right to privacy" doctypes: supremecourt fromdate: 1-1-2017 todate: 31-12-2017'
    ]
    case = result.structured_content["cases"][0]
    assert case["case_id"] == 91938676
    assert case["snippet"] == "the right to privacy is protected as an intrinsic part"  # tags + line breaks gone
    assert case["citation"] == "AIR 2017 SUPREME COURT 4161"


async def test_get_judgment_chunks_long_text_and_strips_html(api):
    long_text = "x" * (server.JUDGMENT_CHUNK_CHARS + 5)
    api.responses["/doc/42/"] = httpx2.Response(
        200,
        json={
            "title": "A vs B",
            "doc": f"<p>Held &amp; dismissed.</p><p>{long_text}</p>",
            "cites": [{"tid": 7, "title": "C vs D"}],  # docs say `citeList`; the live API sends `cites`
        },
    )

    async with Client(server.mcp) as client:
        first = (await client.call_tool("get_judgment", {"case_id": 42})).structured_content
        rest = await client.call_tool("get_judgment", {"case_id": 42, "offset": first["next_offset"]})
        rest = rest.structured_content
        ending = await client.call_tool("get_judgment", {"case_id": 42, "offset": -10})  # jump to the final order
        ending = ending.structured_content

    assert first["text"].startswith("Held & dismissed.\n")
    assert first["next_offset"] == server.JUDGMENT_CHUNK_CHARS
    assert rest["next_offset"] is None
    assert first["text"] + rest["text"] == f"Held & dismissed.\n{long_text}"
    assert first["cites"] == [{"case_id": 7, "title": "C vs D"}]
    assert ending["text"] == "x" * 10
    assert ending["offset"] == first["total_chars"] - 10
    assert ending["next_offset"] is None


async def test_errors_reach_the_model_as_readable_messages(api, monkeypatch):
    api.responses["/search/"] = httpx2.Response(403, json={"errmsg": "Invalid token"})

    async with Client(server.mcp) as client:
        api_error = await client.call_tool("search_cases", {"query": "bail"})
        bad_court = await client.call_tool("search_cases", {"query": "bail", "court": "mars"})
        monkeypatch.setattr(server, "_api", None)
        monkeypatch.delenv("INDIANKANOON_API_TOKEN", raising=False)
        no_token = await client.call_tool("search_cases", {"query": "bail"})

    for result, message in [
        (api_error, "Invalid token"),
        (bad_court, "Unknown court ['mars']"),
        (no_token, "INDIANKANOON_API_TOKEN is not set"),
    ]:
        assert result.is_error
        assert message in result.content[0].text
