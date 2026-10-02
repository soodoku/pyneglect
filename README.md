# pyneglect

[Monthly report](https://gsood.com/pyneglect/) ·
[Workflow runs](https://github.com/soodoku/pyneglect/actions/workflows/monthly.yml)

Monthly discovery of popular Python projects with open issues and recent activity.
A 25-project shortlist and filterable directory link to issues and downloadable
evidence. These are places to investigate, not claims about neglect, staffing,
issue difficulty, or whether a contribution will be accepted.

## Selection

Each edition screens the top 3,000 packages from
[Top PyPI Packages](https://github.com/hugovk/top-pypi-packages). Its current
ClickHouse collector ranks downloads in the **previous calendar month**.
The report records that window and the source update date. A changed source or
stale edition stops collection.

PyPI project metadata maps packages to GitHub, with ecosyste.ms as a fallback.
Packages sharing a repository, including redirected names, become one row.
Downloads are the largest associated package's count, never a sum of siblings or
an estimate of users.

Eligible repositories must:

- Be available, with issues enabled, and not archived, disabled, or a mirror.
- Have at least one open issue (pull requests are counted separately).
- Have a push and an update to a currently open issue within the past 365 days.

The shortlist takes the 25 most downloaded eligible repositories with an open
issue updated within 180 days. Ties use repository name. All eligible repositories
appear in the directory. Corporate projects, foundations, and forks remain eligible.
Contributor counts and contribution labels are filters, not eligibility gates.
There is no weighted score or reward for a larger backlog.

## Run

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and GitHub authentication.
Use `gh auth login`, or set `GH_TOKEN`/`GITHUB_TOKEN` with access to public GitHub data.
No BigQuery, billing account, or paid API is used.

```sh
uv sync --locked
uv run pyneglect run
uv run pyneglect render
python -m http.server --directory site 8000
```

`run` collects/resumes the current UTC month's edition and renders all saved editions.
`render` is completely offline. Open <http://localhost:8000> after starting the server.

For a small live pilot isolated from published editions:

```sh
uv run pyneglect run --limit 20 --state-dir .cache/pilot --snapshots .cache/pilot-snapshots --output .cache/pilot-site
```

Use `--limit` (1–15,000) to change the universe. Use separate snapshot and state
directories for experiments. Completed editions are immutable: another run with
the same configuration reuses the saved snapshot. A different limit cannot overwrite
an edition. Historical collection is not supported: current GitHub observations
cannot reconstruct past issue state.

## Snapshots and failures

`snapshots/YYYY-MM.json` contains a complete edition: source provenance, collection
dates, counts, unmapped packages, exclusion reasons, repository metrics, issue
examples, and optional contributor measurements. Dates are UTC; the download
period end is exclusive. The schema has an explicit version.

`.cache/pyneglect/YYYY-MM.json` checkpoints successful requests within an edition.
Required failures are not cached as misses. A required network, API, or validation
failure exits nonzero before a completed snapshot is written. The previous site
stays published. Rerun to resume. A checkpoint older than seven days must be removed
to collect fresh data; this does not remove completed snapshots.
For a workflow retry after seven days, delete that edition's `monthly-v1-YYYY-MM-…`
checkpoint cache from the repository's Actions caches before dispatching again.

Optional contributor failures do not block publication. Missing values, invalid
counts, or data synced more than 90 days before collection appear as unknown.
Optional collection has a ten-minute budget and stops after a whole batch fails;
uncollected values remain unknown, so an enrichment outage cannot stall publication.
Public snapshots contain discovery fields, not commit-author emails or raw responses.

## Monthly hosting at no service cost

The `Monthly report` workflow runs on the **5th at 08:17 UTC**, with manual dispatch
for retries. Use a **public repository**, standard Linux runner, and GitHub Pages
with **GitHub Actions** as its publishing source. Collection refuses to run in a
private repository. Standard runners for public repositories and public Pages are
free under GitHub's published terms.

The workflow uses `GITHUB_TOKEN`, respects rate limits, and stops if a retry would
require a long wait. Resume with manual dispatch later. Completed snapshots are
committed to the repository. Small checkpoints use the default Actions cache
allowance, with no extra purchased storage. Pages artifacts expire after one day.
There is no paid fallback and no scheduled daily collection.

GitHub can delay scheduled runs or disable schedules after 60 days of inactivity.
Successful monthly snapshot commits keep the repository active. Check failed or
disabled workflows if the report's visible age notice indicates a missed edition.
Do not increase runner size, buy extra cache storage, or make the repo private
without reconsidering the zero-cost constraint.

## Interpretation and coverage

- Downloads include automation and mirrors; caches can suppress counts.
- Issue updates and pushes can come from users or bots. They do not establish
  maintainer engagement, issue quality, or readiness for a contribution.
- Contributor counts are past-year human commit-author identities from ecosyste.ms,
  not maintainers. Identity duplication and source lag affect them. The sync date
  is shown. Zero and unknown are distinct; a contributor limit excludes unknowns.
- Examples show five recently updated open issues, each with up to 20 labels and
  10 assignees. Label filters check exact repository-wide open-issue labels:
  `good first issue`, `good-first-issue`, `help wanted`, and `help-wanted`.
  Labels do not guarantee easy work.
- V1 does not estimate PR acceptance rates, merge latency, or receptiveness.
- Unmapped packages are recorded in the evidence download. External issue trackers
  are outside v1. Monorepo metrics can include non-Python work. PyPI release dates
  refer to the displayed package/version.
- Shortlist entrants/exits compare the preceding saved edition. Changes may reflect
  coverage or eligibility, not project quality.

## Development

```sh
uv sync --locked
make check
make ci-docker
uv run playwright install chromium
uv run python tests/browser_check.py site
```

`make check` runs Ruff linting/format checks, pytest, and
[actionlint](https://github.com/rhysd/actionlint) (install separately). Docker uses
the standard `python:3.12-slim` image. Browser checks require a rendered edition.

Sources: [PyPI JSON API](https://docs.pypi.org/api/json/),
[GitHub GraphQL](https://docs.github.com/en/graphql/reference), and
[ecosyste.ms](https://ecosyste.ms/). ecosyste.ms data is licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); attribution is in
each report. See [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
and [Pages availability](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).
