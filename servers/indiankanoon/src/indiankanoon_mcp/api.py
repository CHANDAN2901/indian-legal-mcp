"""Async client for the IndianKanoon API: https://api.indiankanoon.org/documentation/"""

from __future__ import annotations

import html
import re

import httpx2
from mcp.server.mcpserver.exceptions import ToolError

BASE_URL = "https://api.indiankanoon.org"

# `doctypes` filter values from the API docs. Comma-separated combinations are allowed.
COURTS = frozenset(
    # aggregators
    "judgments highcourts tribunals laws "
    # Supreme Court + High Courts
    "supremecourt scorders delhi bombay kolkata kolkata_app chennai allahabad lucknow andhra chattisgarh gauhati "
    "jammu srinagar kerala orissa uttaranchal gujarat himachal_pradesh jharkhand karnataka madhyapradesh "
    "patna patna_orders punjab rajasthan jodhpur sikkim meghalaya "
    # district courts + tribunals
    "delhidc aptel drat cat cegat stt itat consumer cerc cic clb copyrightboard ipab mrtp sebisat tdsat "
    "trademark greentribunal cci".split()
)

_BLOCK_END = re.compile(r"<br\s*/?>|</(?:p|div|h\d|li|tr|pre|blockquote)>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


class IndianKanoonError(ToolError):
    """An API failure. Subclasses ToolError so the MCP client shows the message to the model."""


def build_query(query: str, court: str | None = None, year: int | None = None) -> str:
    """Filters go inside formInput, the same way the official IKAPI client sends them."""
    if court:
        courts = [c.strip() for c in court.split(",") if c.strip()]
        unknown = set(courts) - COURTS
        if unknown:
            raise IndianKanoonError(f"Unknown court {sorted(unknown)}. Valid values: {', '.join(sorted(COURTS))}")
        query += f" doctypes: {','.join(courts)}"
    if year:
        query += f" fromdate: 1-1-{year} todate: 31-12-{year}"
    return query


def html_to_text(markup: str) -> str:
    """Judgment HTML -> plain text, one line per paragraph."""
    text = html.unescape(_TAG.sub("", _BLOCK_END.sub("\n", markup)))
    return re.sub(r"\s*\n\s*", "\n", re.sub(r"[ \t]+", " ", text)).strip()


class IndianKanoonClient:
    def __init__(self, token: str, transport: httpx2.AsyncBaseTransport | None = None):
        self._http = httpx2.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )

    async def search(self, query: str, court: str | None = None, year: int | None = None, page: int = 0) -> dict:
        return await self._post("/search/", formInput=build_query(query, court, year), pagenum=page)

    async def document(self, doc_id: int) -> dict:
        return await self._post(f"/doc/{doc_id}/", maxcites=5, maxcitedby=5)

    async def _post(self, path: str, **params: str | int) -> dict:
        # Every IndianKanoon endpoint is a POST with its arguments in the query string.
        try:
            response = await self._http.post(path, params=params)
        except httpx2.RequestError as e:
            raise IndianKanoonError(f"Could not reach IndianKanoon ({type(e).__name__}); try again.") from e
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and "errmsg" in data:
            raise IndianKanoonError(f"IndianKanoon API error: {data['errmsg']}")
        if response.is_error or not isinstance(data, dict):
            raise IndianKanoonError(f"IndianKanoon API error {response.status_code}: {response.text[:200]}")
        return data
