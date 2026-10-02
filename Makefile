.PHONY: check test lint ci-docker report
check: lint test

lint:
	uv run ruff check .
	uv run ruff format --check .
	actionlint

test:
	uv run pytest

report:
	uv run pyneglect run

ci-docker:
	docker run --rm -v "$(CURDIR):/app" -w /app python:3.12-slim sh -c 'pip install uv && UV_PROJECT_ENVIRONMENT=/tmp/pyneglect-venv uv sync --locked && UV_PROJECT_ENVIRONMENT=/tmp/pyneglect-venv uv run ruff check . && UV_PROJECT_ENVIRONMENT=/tmp/pyneglect-venv uv run ruff format --check . && UV_PROJECT_ENVIRONMENT=/tmp/pyneglect-venv uv run pytest'
