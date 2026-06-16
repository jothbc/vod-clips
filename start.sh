#!/usr/bin/env bash
# Start the Reels API using the project venv (no `source .venv/bin/activate` needed).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV_REELS="${ROOT}/.venv/bin/reels"
VENV_PY="${ROOT}/.venv/bin/python"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "reels: missing .venv — create it once:" >&2
  echo "  sudo apt install -y python3.10-venv" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e \".[dev,cuda,twitch]\"" >&2
  exit 1
fi

if [[ ! -x "${VENV_REELS}" ]]; then
  echo "reels: installing package into .venv…" >&2
  "${VENV_PY}" -m pip install -q -e ".[dev,cuda,twitch]"
fi

exec "${VENV_REELS}" serve "$@"
