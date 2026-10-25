"""Async client for the Tavily API: https://docs.tavily.com/documentation/api-reference"""

from __future__ import annotations

from typing import Any

import httpx2
from mcp.server.mcpserver.exceptions import ToolError

BASE_URL = "https://api.tavily.com"


class TavilyError(ToolError):
    """An API failure. Subclasses ToolError so the MCP client shows the message to the model."""


class TavilyClient:
    def __init__(self, api_key: str, transport: httpx2.AsyncBaseTransport | None = None):
        self._http = httpx2.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,  # extraction alone may take up to 30s on Tavily's side
            transport=transport,
        )

    async def search(self, query: str, **options: Any) -> dict:
        """POST /search. Options left as None are omitted so Tavily applies its defaults."""
        body = {"query": query, **{k: v for k, v in options.items() if v is not None}}
        return await self._post("/search", body)

    async def extract(self, url: str) -> dict:
        """POST /extract for one URL; returns its result ({url, raw_content})."""
        data = await self._post("/extract", {"urls": [url], "format": "markdown"})
        # A page that can't be read still comes back as HTTP 200, listed under failed_results.
        if not data.get("results"):
            failed = (data.get("failed_results") or [{}])[0]
            raise TavilyError(f"Could not read {url}: {failed.get('error', 'no content returned')}")
        return data["results"][0]

    async def _post(self, path: str, body: dict) -> dict:
        try:
            response = await self._http.post(path, json=body)
        except httpx2.RequestError as e:
            raise TavilyError(f"Could not reach Tavily ({type(e).__name__}); try again.") from e
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.is_error or not isinstance(data, dict):
            # Errors look like {"detail": {"error": "..."}}; 422 validation errors carry a list instead.
            detail = data.get("detail") if isinstance(data, dict) else None
            message = detail.get("error") if isinstance(detail, dict) else detail or response.text[:200]
            raise TavilyError(f"Tavily API error {response.status_code}: {message}")
        return data
