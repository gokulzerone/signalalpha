"""NSE session client.

The exchange's JSON APIs require a session cookie obtained by first requesting the relevant
page, exactly as a browser does. This client performs that warm-up once per host page,
reuses the cookies, and otherwise behaves like :class:`HttpTransport`: it rate-limits,
respects robots.txt, identifies itself, and raises :class:`FetchError` loudly.
"""

from __future__ import annotations

import json
from typing import Any

from data.fetchers.settings import SourceRegistry
from data.fetchers.transport import Fetched, FetchError, HttpTransport


class NseClient(HttpTransport):
    def __init__(self, registry: SourceRegistry, contact: str = "unset") -> None:
        super().__init__(registry, contact)
        self._warmed: set[str] = set()

    def warm_up(self, url: str) -> None:
        """Fetch a site page so the CDN issues session cookies for the API calls."""
        if url in self._warmed:
            return
        self.limiter.wait()
        try:
            self._client.get(url, headers={"Accept": "text/html,application/xhtml+xml"})
        except Exception as exc:
            raise FetchError(url, f"warm-up failed: {exc}") from exc
        self._warmed.add(url)

    def get_json(self, url: str, warmup_url: str | None = None) -> tuple[Any, Fetched]:
        if warmup_url:
            self.warm_up(warmup_url)
        fetched = self.get_with_headers(
            url, {"Referer": warmup_url or self.registry.warmup_url, "Accept": "*/*"}
        )
        try:
            payload = json.loads(fetched.content.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise FetchError(url, "response is not JSON; the endpoint may have changed") from exc
        return payload, fetched
