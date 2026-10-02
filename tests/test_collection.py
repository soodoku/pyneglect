import json
from collections import Counter
from datetime import UTC, datetime

import httpx
import pytest

from pyneglect.client import Client, CollectionError
from pyneglect.collect import GQL, collect, github_batch, github_collect
from pyneglect.model import SOURCE


async def test_http_failure_is_not_a_miss():
    async with Client(
        "secret", transport=httpx.MockTransport(lambda request: httpx.Response(401))
    ) as client:
        with pytest.raises(CollectionError, match="401"):
            await client.request("https://api.github.com/test")


async def test_rate_limit_long_wait_stops():
    async with Client(
        "secret",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"retry-after": "120"})
        ),
    ) as client:
        with pytest.raises(CollectionError, match="resume after"):
            await client.request("https://api.github.com/test")


async def test_token_only_sent_to_github():
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json={})

    async with Client("secret", transport=httpx.MockTransport(handler)) as client:
        await client.request("https://pypi.org/pypi/test/json")


class FakeClient:
    def __init__(self, github_repo):
        self.repo = github_repo
        self.calls = Counter()
        self.fail = True

    async def request(self, url, *, query=None):
        self.calls[url] += 1
        now = datetime.now(UTC)
        if url == SOURCE:
            return {
                "source": "ClickHouse",
                "last_update": now.replace(day=1, hour=0).isoformat(),
                "total_rows": 2,
                "rows": [
                    {"project": "a", "download_count": 100},
                    {"project": "b", "download_count": 50},
                ],
            }
        if "pypi.org/pypi/b/" in url and self.fail:
            raise CollectionError("interrupted")
        if "pypi.org/pypi/" in url:
            return {"info": {"project_urls": {"Source": "https://github.com/example/project"}}}
        if url == GQL:
            return {"data": {"r0": self.repo, "rateLimit": {"remaining": 999}}}
        return None


async def test_resume_does_not_repeat_successful_requests(tmp_path, github_repo):
    client = FakeClient(github_repo)
    month = datetime.now(UTC).strftime("%Y-%m")
    options = dict(
        month=month, limit=2, state_dir=tmp_path / "state", snapshots=tmp_path / "snapshots"
    )
    with pytest.raises(CollectionError, match="interrupted"):
        await collect(client, **options)
    assert not (tmp_path / "snapshots" / f"{month}.json").exists()
    checkpoint = json.loads((tmp_path / "state" / f"{month}.json").read_text())
    assert "a" in checkpoint["mappings"]
    assert "b" not in checkpoint["mappings"]
    client.fail = False
    path = await collect(client, **options)
    snapshot = json.loads(path.read_text())
    assert snapshot["counts"]["eligible"] == 1
    assert snapshot["repositories"][0]["downloads"] == 100
    assert snapshot["repositories"][0]["contributors"] is None
    assert client.calls["https://pypi.org/pypi/a/json"] == 1
    calls = client.calls.copy()
    await collect(client, **options)
    assert client.calls == calls
    with pytest.raises(CollectionError, match="different package limit"):
        await collect(client, **{**options, "limit": 1})


async def test_graphql_partial_response_stops(github_repo):
    class Partial:
        async def request(self, *args, **kwargs):
            return {"data": {"r0": github_repo}, "errors": [{"type": "RATE_LIMITED"}]}

    with pytest.raises(CollectionError):
        await github_batch(Partial(), ["example/project"])


async def test_confirmed_missing_repository():
    class Missing:
        async def request(self, *args, **kwargs):
            return {"data": {"r0": None}, "errors": [{"type": "NOT_FOUND", "path": ["r0"]}]}

    result = await github_batch(Missing(), ["example/project"])
    assert result["example/project"]["unavailable"] is True


async def test_parallel_github_successes_survive_failure(monkeypatch):
    saved = []
    destination = {}

    async def batch(client, slugs):
        if "org/10" in slugs:
            raise CollectionError("retry this batch")
        return {slug: {"repo": slug} for slug in slugs}

    monkeypatch.setattr("pyneglect.collect.github_batch", batch)
    with pytest.raises(CollectionError, match="retry this batch"):
        await github_collect(
            None,
            [f"org/{i}" for i in range(30)],
            destination,
            lambda: saved.append(destination.copy()),
        )
    assert len(destination) == 20
    assert "org/10" not in destination
    assert saved[-1] == destination
