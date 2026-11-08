#!/usr/bin/env bash
# Write local package.lock.json files for every recipe.
# They are gitignored while the bootstrap root follows live Fedora.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}
check=0

case "${1:-}" in
  --check) check=1 ;;
  -h | --help)
    echo "usage: $0 [--check]"
    exit 0
    ;;
  "") ;;
  *)
    echo "unknown argument: $1" >&2
    exit 2
    ;;
esac

for recipe in "$root"/packages/*/package.yaml; do
  [[ -f "$recipe" ]] || continue
  echo "==> lock ${recipe#"$root"/}"
  if ((check)); then
    "$rpmx" lock --check "$recipe"
  else
    "$rpmx" lock "$recipe"
  fi
done
