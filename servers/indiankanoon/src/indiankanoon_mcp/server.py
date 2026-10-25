"""IndianKanoon MCP server: search and read Indian court judgments."""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from indiankanoon_mcp.api import IndianKanoonClient, html_to_text

# Judgments can run past 300k characters; return them in chunks of ~5k tokens.
JUDGMENT_CHUNK_CHARS = 20_000

mcp = MCPServer(
    "indiankanoon",
    instructions=(
        "Search and read Indian court judgments (Supreme Court, High Courts, tribunals) from IndianKanoon. "
        "Use search_cases to find cases, then get_judgment with a case_id to read one. Cite case titles and courts."
    ),
)

_api: IndianKanoonClient | None = None


def _client() -> IndianKanoonClient:
    # Created on first tool call, so a missing token becomes a message Claude can relay instead of a crash.
    global _api
    if _api is None:
        token = os.environ.get("INDIANKANOON_API_TOKEN", "").strip()
        if not token:
            raise ToolError("INDIANKANOON_API_TOKEN is not set. Add it to this server's env in the MCP client config.")
        if not token.isascii():  # e.g. a 'ß' typed by Option+S on a Mac; would otherwise crash in the HTTP header
            raise ToolError("INDIANKANOON_API_TOKEN contains a character that can't be in a token. Paste it again.")
        _api = IndianKanoonClient(token)
    return _api


class Case(BaseModel):
    case_id: int
    title: str
    court: str | None
    date: str | None
    citation: str | None = Field(description="Reporter citation, e.g. 'AIR 2017 SUPREME COURT 4161'")
    author: str | None = Field(description="Judge who wrote the judgment")
    snippet: str = Field(description="Matching excerpt from the judgment")
    cites: int | None = Field(description="How many documents this judgment cites")
    cited_by: int | None = Field(description="How many later documents cite this judgment")


class SearchResults(BaseModel):
    found: str | None = Field(description="Total matches as reported by IndianKanoon")
    page: int
    cases: list[Case]


class CaseRef(BaseModel):
    case_id: int
    title: str


class Judgment(BaseModel):
    case_id: int
    title: str
    court: str | None
    date: str | None
    text: str = Field(description="One chunk of the judgment text, starting at `offset`")
    offset: int
    total_chars: int
    next_offset: int | None = Field(description="Pass as `offset` to read the next chunk; null when finished")
    cites: list[CaseRef] = Field(description="Top documents this judgment cites")
    cited_by: list[CaseRef] = Field(description="Top later documents citing this judgment")


READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@mcp.tool(annotations=READ_ONLY)
async def search_cases(
    query: Annotated[
        str,
        Field(
            description='Search terms. Quote phrases ("right to privacy"); combine with ANDD, ORR, NOTT '
            "(uppercase, spaces on both sides), e.g. 'dowry ANDD murder NOTT acquittal'."
        ),
    ],
    court: Annotated[
        str | None,
        Field(
            description="Restrict to a court: 'supremecourt', 'highcourts' (all High Courts), a single High Court "
            "('delhi', 'bombay', 'chennai', 'kolkata', 'allahabad', 'karnataka', 'kerala', 'gujarat', ...), "
            "'tribunals', or a tribunal ('itat', 'consumer', 'greentribunal', 'cci', ...). Comma-separate to combine."
        ),
    ] = None,
    year: Annotated[int | None, Field(ge=1800, le=2100, description="Only judgments published in this year")] = None,
    page: Annotated[int, Field(ge=0, description="Result page, 0-based; 10 results per page")] = 0,
) -> SearchResults:
    """Search Indian court judgments, tribunal orders and central laws on IndianKanoon.

    Use when the user asks about Indian law, legal precedents, court rulings, or a specific Indian case.
    Returns case_id, title, court, date, citation, author and a matching snippet for each hit; pass a case_id
    to get_judgment to read the full text.
    """
    data = await _client().search(query, court, year, page)
    return SearchResults(
        found=data.get("found"),
        page=page,
        cases=[
            Case(
                case_id=d["tid"],
                title=html_to_text(d.get("title", "")),
                court=d.get("docsource"),
                date=d.get("publishdate"),
                citation=d.get("citation"),
                author=d.get("author"),
                snippet=" ".join(html_to_text(d.get("headline", "")).split()),
                cites=d.get("numcites"),
                cited_by=d.get("numcitedby"),
            )
            for d in data.get("docs") or []
        ],
    )


@mcp.tool(annotations=READ_ONLY)
async def get_judgment(
    case_id: Annotated[
        int,
        Field(gt=0, description="case_id from search_cases, or the number in an indiankanoon.org/doc/<number>/ link"),
    ],
    offset: Annotated[
        int,
        Field(
            description="Character offset to read from: 0 for the start, next_offset to continue, "
            "or negative to count from the end (-20000 reads the final chunk, where the court's order is)"
        ),
    ] = 0,
) -> Judgment:
    """Read the full text of one Indian court judgment by its case_id, plus the cases it cites and is cited by.

    Also use this for any indiankanoon.org/doc/<number>/ link: the number in the link is the case_id.
    Long judgments are returned in 20,000-character chunks. The start covers the parties, bench and facts; the
    final order with the operative holding is at the end. To get the holding, call with offset=-20000 first
    instead of paging through every chunk. Use next_offset to keep reading in order.
    """
    # ponytail: re-fetches the document for every chunk (Rs 0.20/call); cache by case_id if that adds up.
    data = await _client().document(case_id)
    text = html_to_text(data.get("doc", ""))
    if offset < 0:
        offset = max(0, len(text) + offset)
    end = offset + JUDGMENT_CHUNK_CHARS
    return Judgment(
        case_id=case_id,
        title=html_to_text(data.get("title", "")),
        court=data.get("docsource"),
        date=data.get("publishdate"),
        text=text[offset:end],
        offset=offset,
        total_chars=len(text),
        next_offset=end if end < len(text) else None,
        cites=[CaseRef(case_id=c["tid"], title=c.get("title", "")) for c in data.get("cites") or []],
        cited_by=[CaseRef(case_id=c["tid"], title=c.get("title", "")) for c in data.get("citedby") or []],
    )


def main() -> None:
    mcp.run()  # stdio: the client (e.g. Claude Desktop) launches this process and talks over stdin/stdout
