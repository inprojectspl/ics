#!/usr/bin/env bash
# Run the backend lint gates exactly as the lint:backend CI job does.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/backend"
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
