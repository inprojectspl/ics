#!/usr/bin/env bash
# Run frontend unit tests (vitest). Extra arguments select test files, e.g.
# scripts/test-frontend.sh src/components/AssetRow.test.tsx
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/frontend"
exec npx vitest run "$@"
