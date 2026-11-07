#!/usr/bin/env bash
# Emit the in-tree package graph as JSON.
#
# Each package maps to the packages it needs at build time and at run time.
# Edges are resolved through Provides, so a dependency on `system-release` can
# point at `eternal-release`. Only in-tree names are emitted; bootstrap
# packages are not nodes.
#
#   {
#     "eternal-base": {"build": [], "run": ["eternal-baselayout", "eternal-release"]},
#     "eternal-baselayout": {"build": [], "run": []},
#     "eternal-release": {"build": [], "run": []}
#   }
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}

command -v jq >/dev/null 2>&1 || {
  echo "jq is required to compute the package graph" >&2
  exit 1
}

mapfile -t names < <("$root/scripts/list-packages.sh")
if [[ -z ${names[*]-} ]]; then
  echo "no packages found" >&2
  exit 1
fi

declare -A plan provides provider build run

# First pass: collect plans and the capability -> package index.
for name in "${names[@]}"; do
  recipe="$root/packages/$name/package.yaml"
  plan[$name]=$("$rpmx" plan "$recipe" --json 2>/dev/null)
  while IFS= read -r capability; do
    [[ -n $capability ]] && provider[$capability]=$name
  done < <(jq -r '
    .plan.cells[]?.outputs[]?
    | .name, (.provides[]?)
    | capture("^(?<n>[A-Za-z0-9._+-]+)").n
  ' <<<"${plan[$name]}" | sort -u)
done

# Turn a list of capabilities into in-tree package names.
resolve() {
  local capability base
  while IFS= read -r capability; do
    [[ -n $capability ]] || continue
    base=$(sed -E 's/^([A-Za-z0-9._+-]+).*/\1/' <<<"$capability")
    [[ -n ${provider[$base]:-} ]] && printf '%s\n' "${provider[$base]}"
  done
}

# Second pass: resolve edges now that every package has been indexed.
for name in "${names[@]}"; do
  build_raw=$(jq -r '
    .plan.cells[]?
    | (.tools[]?), (.host[]?), (.target[]?), (.test_tools[]?)
  ' <<<"${plan[$name]}")
  run_raw=$(jq -r '
    .plan.cells[]?.outputs[]?
    | (.requires[]?)
  ' <<<"${plan[$name]}")

  build[$name]=$(resolve <<<"$build_raw" | sort -u | grep -vx "$name" | paste -sd' ' - || true)
  run[$name]=$(resolve <<<"$run_raw" | sort -u | grep -vx "$name" | paste -sd' ' - || true)
done

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
for name in "${names[@]}"; do
  printf '%s\t%s\t%s\n' "$name" "${build[$name]:-}" "${run[$name]:-}" >>"$tmp"
done

jq -Rn '
  [inputs
   | split("\t")
   | {key: .[0],
      value: {
        build: (.[1] | split(" ") | map(select(length > 0))),
        run: (.[2] | split(" ") | map(select(length > 0)))
      }}]
  | from_entries
' <"$tmp"
