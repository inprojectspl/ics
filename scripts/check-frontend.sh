#!/usr/bin/env bash
# Run the frontend quality gates as CI does: typecheck, lint, tests with coverage thresholds.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/frontend"
npx tsc --noEmit
npm run lint
npm run test:coverage
