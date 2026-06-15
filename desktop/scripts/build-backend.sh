#!/usr/bin/env bash
# Build the FastAPI backend as a single-file executable using PyInstaller.
# Run from the repo root: cd .. && bash desktop/scripts/build-backend.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT_DIR="$SCRIPT_DIR/../resources/backend"

echo "==> Working directory: $REPO_ROOT"
cd "$REPO_ROOT"

# ── Install PyInstaller if needed ─────────────────────────────────────────
if ! python -c "import PyInstaller" &>/dev/null; then
  echo "==> Installing PyInstaller…"
  pip install pyinstaller
fi

# ── Collect data files ────────────────────────────────────────────────────
DATA_FLAGS=""
if [ -d "crewlayer/db/alembic" ]; then
  DATA_FLAGS="$DATA_FLAGS --add-data crewlayer/db/alembic:crewlayer/db/alembic"
fi
if [ -f "alembic.ini" ]; then
  DATA_FLAGS="$DATA_FLAGS --add-data alembic.ini:."
fi

# ── Build ─────────────────────────────────────────────────────────────────
echo "==> Running PyInstaller…"
pyinstaller main.py \
  --onefile \
  --name crewlayer-backend \
  --distpath dist/backend \
  --workpath /tmp/pyinstaller-work \
  --specpath /tmp/pyinstaller-spec \
  $DATA_FLAGS \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols \
  --hidden-import uvicorn.protocols.http \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan \
  --hidden-import uvicorn.lifespan.on \
  --hidden-import asyncpg \
  --hidden-import aioredis \
  --hidden-import anthropic \
  --collect-all anthropic \
  --noconfirm

# ── Copy to desktop/resources ─────────────────────────────────────────────
mkdir -p "$OUT_DIR"
EXE="dist/backend/crewlayer-backend"
[ "$(uname)" = "MINGW"* ] && EXE="${EXE}.exe"

cp "$EXE" "$OUT_DIR/"
chmod +x "$OUT_DIR/crewlayer-backend" 2>/dev/null || true

echo "==> Done: $OUT_DIR/crewlayer-backend"
echo "    Size: $(du -sh "$OUT_DIR/crewlayer-backend" | cut -f1)"
