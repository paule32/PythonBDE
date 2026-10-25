#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -d .venv ]]; then
  echo "Python-Umgebung fehlt. Bitte einmalig ausführen:"
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
  exit 1
fi
exec .venv/bin/python server.py "$@"
