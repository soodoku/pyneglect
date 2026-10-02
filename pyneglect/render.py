"""Render complete snapshots offline to a static site with downloadable evidence."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, select_autoescape

from .model import shortlist, validate_snapshot


def render(snapshots: Path, output: Path) -> None:
    if output.resolve() == snapshots.resolve() or output.resolve() in snapshots.resolve().parents:
        raise ValueError("Output directory must not contain input snapshots")
    editions = []
    for path in sorted(snapshots.glob("????-??.json")):
        snapshot = json.loads(path.read_text())
        validate_snapshot(snapshot)
        if path.stem != snapshot["month"]:
            raise ValueError("Snapshot filename does not match its edition")
        editions.append(snapshot)
    if not editions:
        raise ValueError("No complete snapshots to render")
    env = Environment(autoescape=select_autoescape(default=True))
    template = env.from_string(files("pyneglect").joinpath("template.html").read_text())
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pyneglect-render-", dir=output.parent) as temporary:
        staged = Path(temporary)
        months = [s["month"] for s in reversed(editions)]
        previous = None
        for snapshot in editions:
            month = snapshot["month"]
            folder = staged / month
            folder.mkdir()
            picks = [r["repo"] for r in shortlist(snapshot)]
            prior = [r["repo"] for r in shortlist(previous)] if previous else []
            payload = {
                **snapshot,
                "shortlist": picks,
                "previous_month": previous["month"] if previous else None,
                "entrants": sorted(set(picks) - set(prior)) if previous else [],
                "exits": sorted(set(prior) - set(picks)) if previous else [],
            }
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            # JSON is embedded inside a script element, not an HTML attribute.
            data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            document = template.render(snapshot=snapshot, months=months, data=data)
            (folder / "index.html").write_text(document)
            (folder / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n")
            with (folder / "candidates.csv").open("w", newline="") as stream:
                columns = [
                    "repo",
                    "package",
                    "downloads",
                    "open_issues",
                    "open_prs",
                    "contributors",
                    "commit_status",
                    "issue_updated_at",
                    "pushed_at",
                    "latest_release_at",
                ]
                writer = csv.DictWriter(stream, columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(r for r in snapshot["repositories"] if not r["exclusions"])
            previous = snapshot
        latest = months[0]
        (staged / "index.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url=./{latest}/">'
            "<title>Pyneglect</title>"
            f'<a href="./{latest}/">Open the {latest} report</a></html>'
        )
        (staged / ".nojekyll").touch()
        # Validation and rendering finish before touching the previous build.
        backup = output.with_name(output.name + ".previous")
        if backup.exists():
            raise ValueError(f"Unexpected backup directory: {backup}")
        if output.exists():
            output.rename(backup)
        try:
            staged.rename(output)
        except OSError:
            if backup.exists():
                backup.rename(output)
            raise
        if backup.exists():
            shutil.rmtree(backup)
