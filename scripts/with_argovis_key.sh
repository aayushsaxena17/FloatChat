#!/usr/bin/env bash
# Run one command with ARGOVIS_API_KEY loaded from the git-ignored .env.txt
# (ADR-0039). The value is never printed or passed as an argument.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env.txt ] || { echo "missing .env.txt" >&2; exit 2; }
key="$(sed -n 's/^[[:space:]]*ARGOVIS_API_KEY[[:space:]]*=[[:space:]]*//p' .env.txt | head -n 1 | tr -d '\r')"
key="${key%\"}"; key="${key#\"}"; key="${key%\'}"; key="${key#\'}"
[ -n "$key" ] || { echo "ARGOVIS_API_KEY not set in .env.txt" >&2; exit 2; }
export ARGOVIS_API_KEY="$key"
unset key
exec "$@"
