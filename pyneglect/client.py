"""Free HTTP APIs with bounded retries. Never turn a failed request into a miss."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential


class CollectionError(RuntimeError):
    """Required collection did not complete; keep the last successful report."""


class Retryable(CollectionError):
    pass


def delay(headers: httpx.Headers) -> float:
    if value := headers.get("retry-after"):
        try:
            return max(0, float(value))
        except ValueError:
            return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    if headers.get("x-ratelimit-remaining") == "0":
        return max(0, float(headers.get("x-ratelimit-reset", 0)) - time.time()) + 1
    return 5


class Client:
    def __init__(self, token: str, *, transport=None):
        self.token = token
        self.http = httpx.AsyncClient(
            headers={"User-Agent": "pyneglect/0.1", "Accept": "application/json"},
            timeout=45,
            follow_redirects=True,
            transport=transport,
        )
        self.calls = Counter()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    async def request(self, url: str, *, query: str | None = None):
        host = urlsplit(url).hostname
        headers = {"Authorization": f"Bearer {self.token}"} if host == "api.github.com" else {}
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=2, max=10),
                retry=retry_if_exception_type((httpx.TransportError, Retryable)),
                reraise=True,
            ):
                with attempt:
                    self.calls[host] += 1
                    response = await self.http.request(
                        "POST" if query else "GET",
                        url,
                        headers=headers,
                        **({"json": {"query": query}} if query else {}),
                    )
                    if response.status_code == 404:
                        return None
                    if response.status_code in {403, 429}:
                        seconds = delay(response.headers)
                        if seconds > 60:
                            raise CollectionError(
                                f"{host}: rate limited; resume after {seconds:.0f}s"
                            )
                        await asyncio.sleep(seconds)
                        raise Retryable(f"{host}: HTTP {response.status_code}")
                    if response.status_code >= 500:
                        raise Retryable(f"{host}: HTTP {response.status_code}")
                    if response.status_code != 200:
                        raise CollectionError(f"{host}: HTTP {response.status_code}")
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise Retryable(f"{host}: invalid JSON") from exc
        except httpx.TransportError as exc:
            raise CollectionError(f"{host}: network request failed") from exc
