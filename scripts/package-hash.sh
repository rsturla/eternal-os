#!/usr/bin/env bash
# Content hash for one or more packages.
#
# The hash covers everything that changes a package's output:
#   - every tracked file under packages/<name>/ (recipe, includes, context);
#   - every profile, because a build-root change can affect any output;
#   - scripts/, because a change to the build entry points is a build change;
#   - the pinned rpmx revision and repository defaults;
#   - the hashes of its in-tree build dependencies, transitively.
#
# It is used both as a local build stamp and as a CI cache key. Two builds with
# the same hash are interchangeable.
#
#   ./scripts/package-hash.sh                 # all packages, "name hash" lines
#   ./scripts/package-hash.sh foo bar         # selected packages
#   ./scripts/package-hash.sh --graph g.json  # reuse a graph
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
graph_file=
names=()

usage() {
  cat <<'EOF'
usage: package-hash.sh [--graph FILE] [NAME...]

  --graph FILE  Reuse a graph produced by package-graph.sh
  -h, --help    Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --graph)
      graph_file=${2:?--graph needs a file}
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      names+=("$1")
      shift
      ;;
  esac
done

command -v jq >/dev/null 2>&1 || {
  echo "jq is required to hash packages" >&2
  exit 1
}

cleanup_graph=0
if [[ -z $graph_file ]]; then
  graph_file=$(mktemp)
  cleanup_graph=1
  "$root/scripts/package-graph.sh" >"$graph_file"
fi

if [[ -z ${names[*]-} ]]; then
  mapfile -t names < <(jq -r 'keys[]' "$graph_file")
fi
for name in "${names[@]}"; do
  jq -e --arg n "$name" 'has($n)' "$graph_file" >/dev/null || {
    echo "unknown package: $name" >&2
    exit 1
  }
done

declare -A own memo
work=$(mktemp -d)
trap 'rm -rf "$work" ${cleanup_graph:+$graph_file}' EXIT

own_hash_for() {
  local name=$1 inner
  if [[ -n ${own[$name]:-} ]]; then
    return
  fi
  inner="$work/own-$name"
  : >"$inner"
  while IFS= read -r -d '' path; do
    printf 'input %s\n' "$path" >>"$inner"
    cat "$root/$path" >>"$inner" 2>/dev/null || true
  done < <(git -C "$root" ls-files -z --cached --others --exclude-standard -- \
    "packages/$name" "packages/openssf-compiler-options" \
    "profiles" "scripts" ".rpmx-revision" "rpmx-defaults.yaml" | sort -z)
  own[$name]=$(sha256sum "$inner" | cut -d' ' -f1)
}

# Hashing a closure rather than recursing through it keeps a dependency cycle
# (make <-> coreutils during bootstrap) from aborting the build. The closure is
# every reachable build dependency; each member contributes its own inputs, so
# a change anywhere in the closure still changes the dependent's hash.
closure_hash() {
  local name=$1 current dep inner
  local -a queue=("$name")
  declare -A seen=()
  seen[$name]=1
  local i=0
  while ((i < ${#queue[@]})); do
    current=${queue[$i]}
    i=$((i + 1))
    while IFS= read -r dep; do
      [[ -n $dep ]] || continue
      if [[ -z ${seen[$dep]:-} ]]; then
        seen[$dep]=1
        queue+=("$dep")
      fi
    done < <(jq -r --arg n "$current" '.[$n].build[]?' "$graph_file")
  done
  inner="$work/closure-$name"
  : >"$inner"
  while IFS= read -r dep; do
    printf 'dependency %s %s\n' "$dep" "${own[$dep]}" >>"$inner"
  done < <(printf '%s\n' "${!seen[@]}" | sort)
  sha256sum "$inner" | cut -d' ' -f1
}

# Every package in the graph may be a dependency of a selected package.
while IFS= read -r name; do
  own_hash_for "$name"
done < <(jq -r 'keys[]' "$graph_file")
for name in "${names[@]}"; do
  memo[$name]=$(closure_hash "$name")
done

for name in "${names[@]}"; do
  printf '%s %s\n' "$name" "${memo[$name]}"
done
