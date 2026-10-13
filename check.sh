#!/usr/bin/env bash
# Cross-platform env check (Linux / WSL / macOS).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ -x "${PY}" ]]; then
  exec "${PY}" "${ROOT}/scripts/env_check.py" "$@"
fi
exec python3 "${ROOT}/scripts/env_check.py" "$@"
