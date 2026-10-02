import json
from copy import deepcopy

import pytest

from pyneglect.model import atomic_json
from pyneglect.render import render


def test_render_escapes_data_and_preserves_old_site(tmp_path, snapshot):
    snapshots = tmp_path / "snapshots"
    output = tmp_path / "site"
    snapshot["repositories"][0]["description"] = '</script><script>alert("bad")</script>'
    path = snapshots / (snapshot["month"] + ".json")
    atomic_json(path, snapshot)
    render(snapshots, output)
    report = output / snapshot["month"] / "index.html"
    original = report.read_text()
    assert '</script><script>alert("bad")' not in original
    assert "\\u003c/script" in original
    assert (report.parent / "candidates.csv").exists()
    assert json.loads((report.parent / "snapshot.json").read_text())["status"] == "complete"
    snapshot["status"] = "partial"
    atomic_json(path, snapshot)
    with pytest.raises(ValueError):
        render(snapshots, output)
    assert report.read_text() == original


def test_archive_and_entrants(tmp_path, snapshot):
    old = deepcopy(snapshot)
    old["month"] = "2025-01"
    old["repositories"][0]["repo"] = "old/project"
    atomic_json(tmp_path / "snapshots" / "2025-01.json", old)
    atomic_json(tmp_path / "snapshots" / f"{snapshot['month']}.json", snapshot)
    render(tmp_path / "snapshots", tmp_path / "site")
    html = (tmp_path / "site" / snapshot["month"] / "index.html").read_text()
    assert '"entrants": ["example/project"]' in html
    assert '"exits": ["old/project"]' in html


def test_empty_directory_renders(tmp_path, snapshot):
    snapshot["repositories"] = []
    snapshot["unmapped"] = [{"package": "project", "reason": "no mapping"}]
    snapshot["counts"].update(repositories=0, eligible=0, unmapped=1)
    atomic_json(tmp_path / "snapshots" / f"{snapshot['month']}.json", snapshot)
    render(tmp_path / "snapshots", tmp_path / "site")
    assert (tmp_path / "site" / "index.html").exists()


def test_output_cannot_replace_snapshots(tmp_path):
    with pytest.raises(ValueError, match="must not contain"):
        render(tmp_path / "snapshots", tmp_path)
