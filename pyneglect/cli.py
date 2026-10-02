"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .client import Client, CollectionError
from .collect import collect
from .render import render


def token() -> str:
    if value := os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        return value
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CollectionError("Set GH_TOKEN or authenticate with gh auth login") from exc
    return result.stdout.strip()


async def run(args):
    async with Client(token()) as client:
        await collect(
            client,
            month=args.month,
            limit=args.limit,
            state_dir=args.state_dir,
            snapshots=args.snapshots,
        )
    render(args.snapshots, args.output)


def main():
    parser = argparse.ArgumentParser(
        description="Monthly discovery of Python projects with open work"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    live = commands.add_parser("run", help="collect/resume the current edition and render")
    live.add_argument("--month", default=datetime.now(UTC).strftime("%Y-%m"))
    live.add_argument("--limit", type=int, default=3000)
    live.add_argument("--state-dir", type=Path, default=Path(".cache/pyneglect"))
    offline = commands.add_parser("render", help="render saved snapshots without network access")
    for command in (live, offline):
        command.add_argument("--snapshots", type=Path, default=Path("snapshots"))
        command.add_argument("--output", type=Path, default=Path("site"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        if args.command == "run":
            asyncio.run(run(args))
        else:
            render(args.snapshots, args.output)
    except (CollectionError, ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Not published: {exc}\n")


if __name__ == "__main__":
    main()
