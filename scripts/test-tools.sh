#!/usr/bin/env bash
# Run helper regressions without compiling package sources.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 -m unittest discover -s "$root/tests" -p 'test_*.py' "$@"
