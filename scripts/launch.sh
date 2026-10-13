#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "HealthEvidence AI — portfolio launch (not for clinical use)"
command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/"; exit 1; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

uv sync --all-extras
(
  cd frontend
  if [[ ! -d node_modules ]]; then
    npm ci
  fi
)

echo "Starting API on :8000 and UI on :5173"
uv run python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
(
  cd frontend
  npm run dev -- --host 127.0.0.1 --port 5173
) &
UI_PID=$!

cleanup() {
  kill "$API_PID" "$UI_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "UI  http://127.0.0.1:5173"
echo "API http://127.0.0.1:8000/docs"
wait
