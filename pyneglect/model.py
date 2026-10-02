"""Pure transformations shared by collection, validation, and rendering."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = 1
SOURCE = (
    "https://raw.githubusercontent.com/hugovk/top-pypi-packages/main/top-pypi-packages.min.json"
)


def dt(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    temporary.replace(path)


def month_start(month: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Month must be YYYY-MM")
    return date.fromisoformat(month + "-01")


def gh_slug(url: str | None) -> str | None:
    if not isinstance(url, str):
        return None
    url = url.strip().removeprefix("git+")
    url = url.replace("git@github.com:", "https://github.com/")
    parsed = urlsplit(url)
    if parsed.hostname != "github.com" or parsed.scheme not in {"http", "https", "ssh", "git"}:
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        return None
    owner, repo = parts[:2]
    repo = repo.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        return None
    if owner.lower() in {"orgs", "users", "topics", "features", "settings"}:
        return None
    return f"{owner}/{repo}".lower()


def package_repo(info: dict) -> str | None:
    urls = info.get("project_urls") or {}
    # Prefer explicit source links over issue trackers or documentation repositories.
    priorities = ("source", "repository", "code", "github", "homepage", "home", "bug", "issue")
    for word in priorities:
        for label, url in urls.items():
            if word in label.lower() and (slug := gh_slug(url)):
                return slug
    return gh_slug(info.get("home_page"))


def ranking(payload: dict, month: str, limit: int, now: datetime) -> dict:
    start = month_start(month)
    updated = dt(payload["last_update"])
    if payload.get("source") != "ClickHouse":
        raise ValueError("Download source changed; verify its measurement window before publishing")
    if updated.strftime("%Y-%m") != month or updated > now:
        raise ValueError("Download source has not advanced to this edition, or has an invalid date")
    rows = payload["rows"]
    if len(rows) < limit or payload.get("total_rows") != len(rows):
        raise ValueError("Download ranking is incomplete")
    packages = []
    seen = set()
    for row in rows:
        name = re.sub(r"[-_.]+", "-", row["project"]).lower()
        count = row["download_count"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or name in seen:
            raise ValueError("Invalid or duplicate package in download ranking")
        if type(count) is not int or count < 0:
            raise ValueError("Invalid download count")
        seen.add(name)
        packages.append({"package": name, "downloads": count})
    packages.sort(key=lambda p: (-p["downloads"], p["package"]))
    return {
        "url": SOURCE,
        "provider": "hugovk/top-pypi-packages (ClickHouse)",
        "updated_at": updated.isoformat(),
        "period_start": (start - timedelta(days=1)).replace(day=1).isoformat(),
        "period_end_exclusive": start.isoformat(),
        "packages": packages[:limit],
    }


def grouped(packages: list[dict], mappings: dict) -> list[dict]:
    repos = {}
    for package in packages:
        slug = mappings[package["package"]].get("repo")
        if slug:
            repos.setdefault(slug.lower(), []).append(package)
    result = []
    for slug, members in repos.items():
        members.sort(key=lambda p: (-p["downloads"], p["package"]))
        result.append({"repo": slug, **members[0], "packages": members})
    return sorted(result, key=lambda r: (-r["downloads"], r["repo"]))


def recent(value: str | None, as_of: datetime, days: int) -> bool:
    return bool(value and as_of - timedelta(days=days) <= dt(value) <= as_of)


def exclusions(repo: dict, as_of: datetime) -> list[str]:
    if repo.get("unavailable"):
        return ["repository unavailable"]
    reasons = []
    for key in ("archived", "disabled", "mirror"):
        if repo[key]:
            reasons.append(key)
    if not repo["issues_enabled"]:
        reasons.append("issues disabled")
    if repo["open_issues"] < 1:
        reasons.append("no open issues")
    if not recent(repo["pushed_at"], as_of, 365):
        reasons.append("no push within 365 days")
    if not recent(repo["issue_updated_at"], as_of, 365):
        reasons.append("no open issue updated within 365 days")
    return reasons


def validate_snapshot(snapshot: dict) -> None:
    if snapshot["schema"] != SCHEMA or snapshot["status"] != "complete":
        raise ValueError("Only complete, supported snapshots may be rendered")
    month_start(snapshot["month"])
    rows = snapshot["repositories"]
    if len({r["repo"].lower() for r in rows}) != len(rows):
        raise ValueError("Duplicate repositories")
    counts = snapshot["counts"]
    package_names = [p["package"] for row in rows for p in row["packages"]]
    package_names.extend(p["package"] for p in snapshot["unmapped"])
    if (
        counts["packages"] != snapshot["limit"]
        or len(package_names) != snapshot["limit"]
        or len(set(package_names)) != len(package_names)
        or counts["repositories"] != len(rows)
        or counts["unmapped"] != len(snapshot["unmapped"])
        or counts["eligible"] != sum(not row["exclusions"] for row in rows)
    ):
        raise ValueError("Incomplete package collection")
    for row in rows:
        if row["downloads"] != max(p["downloads"] for p in row["packages"]):
            raise ValueError("Repository download count must use its largest package")
        if row["exclusions"] != exclusions(row, dt(snapshot["as_of"])):
            raise ValueError("Inconsistent eligibility")


def shortlist(snapshot: dict) -> list[dict]:
    as_of = dt(snapshot["as_of"])
    candidates = [
        r
        for r in snapshot["repositories"]
        if not r["exclusions"] and recent(r["issue_updated_at"], as_of, 180)
    ]
    return sorted(candidates, key=lambda r: (-r["downloads"], r["repo"]))[:25]
