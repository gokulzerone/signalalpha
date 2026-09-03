"""HTTP transport for live sources (PRD §5.2 legal and ToS compliance).

Identifies itself with a User-Agent, respects robots.txt, rate-limits, and fails loudly with
:class:`FetchError`. Fetched bytes are returned verbatim so callers can store them raw-first.
An in-memory :class:`FakeTransport` supports tests with no network.
"""

from __future__ import annotations

import threading
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from data.fetchers.settings import SourceRegistry


class FetchError(RuntimeError):
    def __init__(self, url: str, reason: str, status: int | None = None) -> None:
        super().__init__(f"{reason} ({url})")
        self.url = url
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class Fetched:
    url: str
    status: int
    content: bytes
    content_type: str


class Transport(Protocol):
    def get(self, url: str) -> Fetched: ...


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(1, per_minute)
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._times and now - self._times[0] > 60:
                self._times.popleft()
            if len(self._times) >= self.per_minute:
                time.sleep(60 - (now - self._times[0]))
            self._times.append(time.monotonic())


class HttpTransport:
    def __init__(self, registry: SourceRegistry, contact: str = "unset") -> None:
        self.registry = registry
        self.user_agent = registry.user_agent.replace("set SIGNALALPHA_CONTACT", contact)
        self.limiter = RateLimiter(registry.rate_limit_per_minute)
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept": "*/*"},
            timeout=registry.request_timeout_seconds,
            follow_redirects=True,
        )

    def allowed(self, url: str) -> bool:
        if not self.registry.respect_robots:
            return True
        origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                resp = self._client.get(f"{origin}/robots.txt")
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                    self._robots[origin] = parser
                else:
                    self._robots[origin] = None  # no robots file: allowed
            except httpx.HTTPError:
                self._robots[origin] = None
        rp = self._robots[origin]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def get(self, url: str) -> Fetched:
        if not self.allowed(url):
            raise FetchError(url, "disallowed by robots.txt")
        self.limiter.wait()
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise FetchError(url, f"network error: {exc}") from exc
        if resp.status_code != 200:
            raise FetchError(url, f"unexpected status {resp.status_code}", resp.status_code)
        if not resp.content:
            raise FetchError(url, "empty response body", resp.status_code)
        return Fetched(
            url,
            resp.status_code,
            resp.content,
            resp.headers.get("content-type", "application/octet-stream"),
        )


class FakeTransport:
    """Serves canned responses; records every URL requested."""

    def __init__(
        self, responses: dict[str, bytes | Exception], content_type: str = "text/plain"
    ) -> None:
        self.responses = responses
        self.content_type = content_type
        self.requested: list[str] = []

    def get(self, url: str) -> Fetched:
        self.requested.append(url)
        body = self.responses.get(url)
        if body is None:
            raise FetchError(url, "unexpected status 404", 404)
        if isinstance(body, Exception):
            raise body
        return Fetched(url, 200, body, self.content_type)
