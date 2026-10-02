"""Collect one edition, checkpoint successful requests, then commit a snapshot."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from .client import Client, CollectionError
from .model import (
    SCHEMA,
    SOURCE,
    atomic_json,
    dt,
    exclusions,
    gh_slug,
    grouped,
    month_start,
    package_repo,
    ranking,
    validate_snapshot,
)

LOG = logging.getLogger(__name__)
GQL = "https://api.github.com/graphql"
ECOPACKAGES = "https://packages.ecosyste.ms/api/v1/registries/pypi.org/packages/"
ECOCOMMITS = "https://commits.ecosyste.ms/api/v1/hosts/GitHub/repositories/"
FIELDS = """
nameWithOwner description isPrivate isArchived isDisabled isMirror isFork hasIssuesEnabled pushedAt
issues(states:OPEN, first:5, orderBy:{field:UPDATED_AT,direction:DESC}) {
  totalCount nodes {
    number title url updatedAt
    labels(first:20) { nodes { name } }
    assignees(first:10) { totalCount nodes { login } }
  }
}
pullRequests(states:OPEN) { totalCount }
gfi: issues(states:OPEN, labels:["good first issue"]) { totalCount }
gfiAlt: issues(states:OPEN, labels:["good-first-issue"]) { totalCount }
help: issues(states:OPEN, labels:["help wanted"]) { totalCount }
helpAlt: issues(states:OPEN, labels:["help-wanted"]) { totalCount }
"""


def query(slugs: list[str]) -> str:
    parts = ["query { rateLimit { remaining cost resetAt }"]
    for i, slug in enumerate(slugs):
        owner, name = slug.split("/", 1)
        parts.append(
            f"r{i}: repository(owner:{json.dumps(owner)},name:{json.dumps(name)})"
            + "{"
            + FIELDS
            + "}"
        )
    return "\n".join(parts) + "}"


def summarize(repo: dict) -> dict:
    if repo["isPrivate"]:
        return {"repo": repo["nameWithOwner"].lower(), "unavailable": True}
    issues = repo["issues"]
    nodes = issues["nodes"]
    if issues["totalCount"] > 0 and not nodes:
        raise CollectionError("GitHub returned an issue count without issue examples")
    return {
        "repo": repo["nameWithOwner"].lower(),
        "description": repo["description"] or "",
        "archived": repo["isArchived"],
        "disabled": repo["isDisabled"],
        "mirror": repo["isMirror"],
        "fork": repo["isFork"],
        "issues_enabled": repo["hasIssuesEnabled"],
        "pushed_at": repo["pushedAt"],
        "open_issues": issues["totalCount"],
        "open_prs": repo["pullRequests"]["totalCount"],
        "issue_updated_at": nodes[0]["updatedAt"] if nodes else None,
        "has_good_first_issue": any(repo[k]["totalCount"] > 0 for k in ("gfi", "gfiAlt")),
        "has_help_wanted": any(repo[k]["totalCount"] > 0 for k in ("help", "helpAlt")),
        "issues": [
            {
                "number": n["number"],
                "title": n["title"],
                "url": n["url"],
                "updated_at": n["updatedAt"],
                "labels": [x["name"] for x in n["labels"]["nodes"]],
                "assignees": [x["login"] for x in n["assignees"]["nodes"]],
                "assignee_count": n["assignees"]["totalCount"],
            }
            for n in nodes
        ],
        "observed_at": datetime.now(UTC).isoformat(),
    }


async def github_batch(client: Client, slugs: list[str]) -> dict:
    payload = await client.request(GQL, query=query(slugs))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise CollectionError("GitHub query failed; no complete data returned")
    data = payload["data"]
    errors = payload.get("errors") or []
    missing = set()
    for error in errors:
        path = error.get("path") or []
        if error.get("type") == "NOT_FOUND" and len(path) == 1:
            missing.add(path[0])
        else:
            raise CollectionError(f"GitHub query error: {error.get('message', 'unknown error')}")
    result = {}
    for i, slug in enumerate(slugs):
        alias = f"r{i}"
        if alias in missing:
            result[slug] = {"repo": slug, "unavailable": True}
        elif data.get(alias) is not None:
            result[slug] = summarize(data[alias])
        else:
            raise CollectionError(f"Missing GitHub response for {slug}; retry required")
    rate = data.get("rateLimit") or {}
    LOG.info("GitHub: %d repositories, %s points remaining", len(slugs), rate.get("remaining"))
    return result


async def github_collect(client: Client, slugs: list[str], destination: dict, save) -> None:
    todo = [slug for slug in slugs if slug not in destination]
    for offset in range(0, len(todo), 30):
        chunks = [
            todo[i : min(i + 10, offset + 30)]
            for i in range(offset, min(offset + 30, len(todo)), 10)
        ]
        results = await asyncio.gather(
            *(github_batch(client, chunk) for chunk in chunks), return_exceptions=True
        )
        failures = []
        for result in results:
            if isinstance(result, BaseException):
                failures.append(result)
            else:
                destination.update(result)
        save()
        if failures:
            raise CollectionError(str(failures[0])) from failures[0]
        await asyncio.sleep(1)


async def mapping(client: Client, package: str) -> dict:
    payload = await client.request(f"https://pypi.org/pypi/{package}/json")
    if payload is None:
        return {"repo": None, "reason": "package unavailable on PyPI"}
    info = payload["info"]
    slug = package_repo(info)
    via = "PyPI project metadata"
    if not slug:
        # Mapping is required. If its fallback fails, retry the package on resume.
        eco = await client.request(ECOPACKAGES + package)
        slug = gh_slug((eco or {}).get("repository_url"))
        via = "ecosyste.ms package metadata"
    releases = [r.get("upload_time_iso_8601") for r in payload.get("urls", [])]
    return {
        "repo": slug,
        "via": via,
        "reason": None if slug else "no supported GitHub mapping",
        "latest_release_at": max((x for x in releases if x), default=None),
    }


def commit_metrics(payload: dict | None, now: datetime) -> dict:
    unknown = {"contributors": None, "commits_synced_at": None, "commit_status": "missing"}
    if not payload:
        return unknown
    synced = payload.get("last_synced_at")
    if not synced:
        return unknown
    age = now - dt(synced)
    status = "fresh" if timedelta(0) <= age <= timedelta(days=90) else "stale"
    human = payload.get("past_year_total_committers")
    bots = payload.get("past_year_total_bot_committers")
    count = human - bots if type(human) is int and type(bots) is int else None
    if count is None or count < 0:
        status = "missing"
    return {
        "contributors": count if status == "fresh" else None,
        "commits_synced_at": synced,
        "commit_status": status,
    }


async def optional_commits(client: Client, slug: str) -> dict:
    try:
        async with asyncio.timeout(20):
            payload = await client.request(ECOCOMMITS + quote(slug, safe=""))
        return commit_metrics(payload, datetime.now(UTC))
    except (CollectionError, ValueError, TypeError, TimeoutError):
        LOG.warning("Optional contributor data unavailable for %s", slug)
        return {"contributors": None, "commits_synced_at": None, "commit_status": "unavailable"}


async def enrich(client: Client, slugs: list[str], destination: dict, save) -> None:
    todo = [slug for slug in slugs if slug not in destination]
    deadline = time.monotonic() + 600
    for offset in range(0, len(todo), 4):
        if time.monotonic() >= deadline:
            LOG.warning("Optional contributor collection reached its 10-minute time budget")
            break
        chunk = todo[offset : offset + 4]
        results = await asyncio.gather(*(optional_commits(client, slug) for slug in chunk))
        destination.update(zip(chunk, results, strict=True))
        save()
        if all(result["commit_status"] == "unavailable" for result in results):
            LOG.warning(
                "Optional contributor service unavailable; keeping remaining values unknown"
            )
            break
        if offset % 80 == 0 or offset + 4 >= len(todo):
            LOG.info("Contributor records: %d/%d", len(destination), len(slugs))
        await asyncio.sleep(1)
    for slug in todo:
        destination.setdefault(
            slug,
            {
                "contributors": None,
                "commits_synced_at": None,
                "commit_status": "not collected",
            },
        )
    save()


async def batches(items, fetch, destination: dict, save, size=8):
    todo = [item for item in items if item not in destination]
    for offset in range(0, len(todo), size):
        chunk = todo[offset : offset + size]
        results = await asyncio.gather(*(fetch(item) for item in chunk), return_exceptions=True)
        failures = []
        for item, result in zip(chunk, results, strict=True):
            if isinstance(result, BaseException):
                failures.append(result)
            else:
                destination[item] = result
        save()
        if failures:
            raise CollectionError(str(failures[0])) from failures[0]
        if offset % 80 == 0 or offset + size >= len(todo):
            LOG.info("Collected %d/%d records", len(destination), len(items))
        await asyncio.sleep(0.25)


async def collect(
    client: Client,
    *,
    month: str,
    limit: int,
    state_dir: Path,
    snapshots: Path,
) -> Path:
    now = datetime.now(UTC)
    month_start(month)
    if month != now.strftime("%Y-%m"):
        raise CollectionError("Live collection is only valid for the current UTC month")
    if not 1 <= limit <= 15000:
        raise ValueError("limit must be between 1 and 15000")
    output = snapshots / f"{month}.json"
    if output.exists():
        existing = json.loads(output.read_text())
        validate_snapshot(existing)
        if existing["limit"] != limit:
            raise CollectionError("This edition already exists with a different package limit")
        LOG.info("Edition %s already complete; using its saved snapshot", month)
        return output
    checkpoint = state_dir / f"{month}.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state["schema"] != SCHEMA or state["limit"] != limit or state["month"] != month:
            raise CollectionError(
                "Checkpoint configuration differs; use a separate state directory"
            )
        if now - dt(state["started_at"]) > timedelta(days=7):
            raise CollectionError("Checkpoint is over 7 days old; remove it to collect fresh data")
    else:
        source = ranking(await client.request(SOURCE), month, limit, now)
        state = {
            "schema": SCHEMA,
            "month": month,
            "limit": limit,
            "source": source,
            "started_at": now.isoformat(),
            "mappings": {},
            "github": {},
            "commits": {},
        }

    def save():
        atomic_json(checkpoint, state)

    save()
    packages = state["source"]["packages"]
    await batches(
        [p["package"] for p in packages],
        lambda p: mapping(client, p),
        state["mappings"],
        save,
    )
    repos = grouped(packages, state["mappings"])
    await github_collect(client, [r["repo"] for r in repos], state["github"], save)

    # Canonical GitHub names also collapse renamed repositories referenced by old URLs.
    canonical = {}
    for repo in repos:
        metadata = state["github"][repo["repo"]]
        slug = metadata["repo"]
        if slug not in canonical:
            canonical[slug] = {**repo, **metadata, "packages": list(repo["packages"])}
        else:
            canonical[slug]["packages"].extend(repo["packages"])
    observed = datetime.now(UTC)
    eligible = [slug for slug, r in canonical.items() if not exclusions(r, observed)]
    await enrich(client, eligible, state["commits"], save)
    as_of = datetime.now(UTC)
    rows = []
    for slug, repo in canonical.items():
        members = sorted(repo["packages"], key=lambda p: (-p["downloads"], p["package"]))
        repo.update(members[0])
        repo["packages"] = members
        repo["latest_release_at"] = state["mappings"][repo["package"]].get("latest_release_at")
        repo.update(state["commits"].get(slug, commit_metrics(None, as_of)))
        repo["exclusions"] = exclusions(repo, as_of)
        rows.append(repo)
    rows.sort(key=lambda r: (-r["downloads"], r["repo"]))
    unmapped = [
        {**p, **state["mappings"][p["package"]]}
        for p in packages
        if not state["mappings"][p["package"]]["repo"]
    ]
    snapshot = {
        "schema": SCHEMA,
        "status": "complete",
        "month": month,
        "limit": limit,
        "started_at": state["started_at"],
        "as_of": as_of.isoformat(),
        "source": {k: v for k, v in state["source"].items() if k != "packages"},
        "counts": {
            "packages": len(packages),
            "repositories": len(rows),
            "eligible": sum(not r["exclusions"] for r in rows),
            "unmapped": len(unmapped),
        },
        "requests_this_attempt": dict(client.calls),
        "repositories": rows,
        "unmapped": unmapped,
    }
    validate_snapshot(snapshot)
    atomic_json(output, snapshot)
    LOG.info("Completed %s: %s", month, snapshot["counts"])
    return output
