#!/usr/bin/env bash
# API + Vite dev server in one terminal (Ctrl+C stops both).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
    kill "${API_PID}" 2>/dev/null || true
    wait "${API_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"${ROOT}/start.sh" "$@" &
API_PID=$!

sleep 1

cd "${ROOT}/web"
if [[ ! -d node_modules ]]; then
  echo "reels: npm install in web/…" >&2
  npm install
fi

echo "reels: API → http://127.0.0.1:8000 (or --port)" >&2
echo "reels: UI  → http://127.0.0.1:5173" >&2
exec npm run dev
