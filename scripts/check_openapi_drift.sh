#!/usr/bin/env bash
# Verify docs/openapi.json matches the live FastAPI spec.
#
# Exit 0 if in sync; non-zero with a unified diff if stale. Called by
# .github/workflows/ci.yml — PRs that touch routes must regenerate the
# committed artifact.
#
# Regenerate locally with:
#     python scripts/export_openapi.py > docs/openapi.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMITTED="$REPO_ROOT/docs/openapi.json"
LIVE="$(mktemp -t openapi-live.XXXXXX.json)"
trap 'rm -f "$LIVE"' EXIT

# Run the exporter from $REPO_ROOT but the script itself chdir's to a
# .env-free directory before importing the FastAPI app.
if ! python "$REPO_ROOT/scripts/export_openapi.py" > "$LIVE"; then
  echo "✗ export_openapi.py failed — fix the import before checking drift"
  exit 2
fi

if [ ! -f "$COMMITTED" ]; then
  echo "✗ $COMMITTED is missing. Generate it:"
  echo "    python scripts/export_openapi.py > $COMMITTED"
  exit 1
fi

if diff -u "$COMMITTED" "$LIVE" > /dev/null; then
  echo "✓ $COMMITTED is in sync with the live FastAPI spec."
  exit 0
fi

echo "✗ $COMMITTED is stale — the FastAPI app has changed since the last regen."
echo ""
echo "──────── diff (committed → live) ────────"
diff -u "$COMMITTED" "$LIVE" | head -80 || true
echo "──────── end diff (truncated to 80 lines) ────────"
echo ""
echo "To fix: python scripts/export_openapi.py > $COMMITTED"
exit 1
