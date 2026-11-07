#!/usr/bin/env bash
# Print the package names that have a recipe, one per line. CI and the local
# build scripts use this so the matrix and a full build agree.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

for recipe in "$root"/packages/*/package.yaml; do
  [[ -f "$recipe" ]] || continue
  basename "$(dirname "$recipe")"
done
