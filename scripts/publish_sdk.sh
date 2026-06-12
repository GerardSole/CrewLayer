#!/usr/bin/env bash
# Manual publish script for the CrewLayer Python SDK.
#
# Prerequisites:
#   pip install build twine
#   A valid ~/.pypirc or TWINE_USERNAME / TWINE_PASSWORD env vars
#   (or use `twine upload --repository testpypi` to test first)
#
# Usage:
#   bash scripts/publish_sdk.sh                  # upload to PyPI
#   bash scripts/publish_sdk.sh --test           # upload to TestPyPI
#   bash scripts/publish_sdk.sh --check-only     # build + check, no upload

set -euo pipefail

REPO="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$SCRIPT_DIR/../sdk"

cd "$SDK_DIR"
echo "Working in: $(pwd)"

# ── 1. Clean previous builds ──────────────────────────────────────────────
echo ""
echo "==> Cleaning dist/"
rm -rf dist/ build/ crewlayer.egg-info/

# ── 2. Build wheel + sdist ────────────────────────────────────────────────
echo ""
echo "==> Building..."
python -m build

echo ""
echo "Built:"
ls -lh dist/

# ── 3. Check metadata + README rendering ─────────────────────────────────
echo ""
echo "==> Checking distribution..."
python -m twine check dist/*

if [[ "$REPO" == "--check-only" ]]; then
    echo ""
    echo "Check complete. No upload (--check-only)."
    exit 0
fi

# ── 4. Upload ─────────────────────────────────────────────────────────────
echo ""
if [[ "$REPO" == "--test" ]]; then
    echo "==> Uploading to TestPyPI..."
    python -m twine upload --repository testpypi dist/*
    echo ""
    echo "Done. Check: https://test.pypi.org/project/crewlayer/"
    echo "Install from TestPyPI:"
    echo "  pip install --index-url https://test.pypi.org/simple/ crewlayer"
else
    echo "==> Uploading to PyPI..."
    python -m twine upload dist/*
    echo ""
    echo "Done. Check: https://pypi.org/project/crewlayer/"
    echo "Install:"
    echo "  pip install crewlayer"
fi
