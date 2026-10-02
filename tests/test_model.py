from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from pyneglect.collect import commit_metrics, summarize
from pyneglect.model import (
    dt,
    exclusions,
    gh_slug,
    grouped,
    package_repo,
    ranking,
    recent,
    shortlist,
    validate_snapshot,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/Org/Repo.git", "org/repo"),
        ("git+https://github.com/Org/Repo/tree/main/src", "org/repo"),
        ("git@github.com:Org/Repo.git", "org/repo"),
        ("https://github.com/org/repo/issues", "org/repo"),
        ("https://github.com.evil.test/org/repo", None),
        ("https://evil.test/github.com/org/repo", None),
        ("https://github.com/orgs/org", None),
        (None, None),
    ],
)
def test_github_url(url, expected):
    assert gh_slug(url) == expected


def test_mapping_prefers_source():
    assert (
        package_repo(
            {
                "project_urls": {
                    "Documentation": "https://github.com/docs/docs",
                    "Source Code": "https://github.com/org/repo",
                }
            }
        )
        == "org/repo"
    )


def test_download_window_and_validation():
    now = datetime(2026, 3, 5, tzinfo=UTC)
    payload = {
        "last_update": "2026-03-01 12:00:00",
        "source": "ClickHouse",
        "total_rows": 2,
        "rows": [{"project": "b", "download_count": 20}, {"project": "A_b", "download_count": 30}],
    }
    result = ranking(payload, "2026-03", 2, now)
    assert result["period_start"] == "2026-02-01"
    assert result["period_end_exclusive"] == "2026-03-01"
    assert result["packages"][0]["package"] == "a-b"
    with pytest.raises(ValueError, match="advanced"):
        ranking(payload, "2026-04", 2, now)
    with pytest.raises(ValueError, match="incomplete"):
        ranking(payload, "2026-03", 3, now)
    payload["source"] = "unknown"
    with pytest.raises(ValueError, match="source changed"):
        ranking(payload, "2026-03", 2, now)


def test_grouping_uses_maximum_not_sum():
    packages = [{"package": "a", "downloads": 100}, {"package": "b", "downloads": 50}]
    rows = grouped(packages, {"a": {"repo": "Org/Repo"}, "b": {"repo": "org/repo"}})
    assert len(rows) == 1
    assert rows[0]["downloads"] == 100
    assert len(rows[0]["packages"]) == 2


def test_date_boundaries():
    now = datetime(2026, 10, 5, tzinfo=UTC)
    assert recent((now - timedelta(days=365)).isoformat(), now, 365)
    assert not recent((now - timedelta(days=365, seconds=1)).isoformat(), now, 365)
    assert not recent((now + timedelta(seconds=1)).isoformat(), now, 365)
    assert not recent(None, now, 365)


def test_eligibility_no_team_or_org_exclusion(snapshot):
    row = snapshot["repositories"][0]
    row.update(repo="microsoft/project", contributors=1000, fork=True)
    assert exclusions(row, dt(snapshot["as_of"])) == []
    row["archived"] = True
    assert "archived" in exclusions(row, dt(snapshot["as_of"]))
    row.update(archived=False, open_issues=0)
    assert "no open issues" in exclusions(row, dt(snapshot["as_of"]))


def test_prs_are_not_issues(github_repo):
    result = summarize(github_repo)
    assert result["open_issues"] == 2
    assert result["open_prs"] == 17
    assert result["has_good_first_issue"] is True  # Label not present in the example.


def test_shortlist_recent_and_deterministic(snapshot):
    row = snapshot["repositories"][0]
    twin = deepcopy(row)
    twin["repo"] = "a/project"
    snapshot["repositories"] = [row, twin]
    assert shortlist(snapshot)[0]["repo"] == "a/project"
    twin["issue_updated_at"] = (dt(snapshot["as_of"]) - timedelta(days=181)).isoformat()
    assert len(shortlist(snapshot)) == 1


def test_commit_counts_unknown_and_zero():
    now = datetime.now(UTC)
    assert commit_metrics(None, now)["contributors"] is None
    payload = {
        "last_synced_at": now.isoformat(),
        "past_year_total_committers": 1,
        "past_year_total_bot_committers": 1,
    }
    assert commit_metrics(payload, now)["contributors"] == 0
    payload["last_synced_at"] = (now - timedelta(days=91)).isoformat()
    assert commit_metrics(payload, now)["contributors"] is None
    assert commit_metrics(payload, now)["commit_status"] == "stale"


def test_reject_incomplete_snapshot(snapshot):
    snapshot["status"] = "partial"
    with pytest.raises(ValueError):
        validate_snapshot(snapshot)


def test_private_details_are_not_saved(github_repo):
    github_repo["isPrivate"] = True
    result = summarize(github_repo)
    assert result == {"repo": "example/project", "unavailable": True}


def test_snapshot_accounts_for_every_package(snapshot):
    snapshot["repositories"] = []
    snapshot["counts"].update(repositories=0, eligible=0)
    with pytest.raises(ValueError, match="Incomplete"):
        validate_snapshot(snapshot)
