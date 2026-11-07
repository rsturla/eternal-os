#!/usr/bin/env bash
# Validate every recipe in the repository, including bootstrap variants.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}

args=()
while (($# > 0)); do
  case "$1" in
    --strict) args+=(--strict) ;;
    -h | --help)
      echo "usage: $0 [--strict]"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

found=0
for recipe in "$root"/packages/*/package.yaml "$root"/bootstrap/recipes/*/package.yaml; do
  [[ -f "$recipe" ]] || continue
  found=1
  echo "==> lint ${recipe#"$root"/}"
  "$rpmx" lint "$recipe" "${args[@]}"
done

if ((found == 0)); then
  echo "no recipes found under packages/ or bootstrap/recipes/" >&2
  exit 1
fi
