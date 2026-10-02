from datetime import UTC, datetime

import pytest

from pyneglect.collect import summarize
from pyneglect.model import SCHEMA, exclusions


@pytest.fixture
def github_repo():
    now = datetime.now(UTC).isoformat()
    return {
        "nameWithOwner": "example/project",
        "description": "A project",
        "isArchived": False,
        "isPrivate": False,
        "isDisabled": False,
        "isMirror": False,
        "isFork": False,
        "hasIssuesEnabled": True,
        "pushedAt": now,
        "issues": {
            "totalCount": 2,
            "nodes": [
                {
                    "number": 1,
                    "title": "Please fix this",
                    "url": "https://github.com/example/project/issues/1",
                    "updatedAt": now,
                    "labels": {"nodes": [{"name": "bug"}]},
                    "assignees": {"totalCount": 0, "nodes": []},
                }
            ],
        },
        "pullRequests": {"totalCount": 17},
        "gfi": {"totalCount": 1},
        "gfiAlt": {"totalCount": 0},
        "help": {"totalCount": 0},
        "helpAlt": {"totalCount": 0},
    }


@pytest.fixture
def snapshot(github_repo):
    now = datetime.now(UTC)
    row = {
        **summarize(github_repo),
        "downloads": 100,
        "package": "project",
        "packages": [{"package": "project", "downloads": 100}],
        "contributors": None,
        "commits_synced_at": None,
        "commit_status": "missing",
        "latest_release_at": None,
    }
    row["exclusions"] = exclusions(row, now)
    return {
        "schema": SCHEMA,
        "status": "complete",
        "month": now.strftime("%Y-%m"),
        "limit": 1,
        "as_of": now.isoformat(),
        "started_at": now.isoformat(),
        "counts": {"packages": 1, "repositories": 1, "eligible": 1, "unmapped": 0},
        "source": {
            "period_start": "2026-09-01",
            "period_end_exclusive": "2026-10-01",
            "updated_at": now.isoformat(),
        },
        "repositories": [row],
        "unmapped": [],
    }
