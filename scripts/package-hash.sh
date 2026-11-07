#!/usr/bin/env bash
# Content hash for one or more packages.
#
# The hash covers everything that changes a package's output:
#   - every file under packages/<name>/ (recipe, includes, context, lock);
#   - every profile, because a build-root change can affect any output;
#   - scripts/, because a change to the build entry points is a build change;
#   - the pinned rpmx revision;
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
rpmx=${RPMX:-rpmx}
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

declare -A memo visiting
work=$(mktemp -d)
trap 'rm -rf "$work" ${cleanup_graph:+$graph_file}' EXIT

hash_for() {
  local name=$1 dep inner
  if [[ -n ${memo[$name]:-} ]]; then
    return
  fi
  if [[ -n ${visiting[$name]:-} ]]; then
    echo "package graph contains a cycle at '$name'" >&2
    exit 1
  fi
  visiting[$name]=1

  inner="$work/$name"
  : >"$inner"

  while IFS= read -r dep; do
    [[ -n $dep ]] || continue
    hash_for "$dep"
    printf 'dependency %s %s\n' "$dep" "${memo[$dep]}" >>"$inner"
  done < <(jq -r --arg n "$name" '.[$n].build[]?' "$graph_file")

  while IFS= read -r -d '' path; do
    printf 'input %s\n' "$path" >>"$inner"
    cat "$root/$path" >>"$inner" 2>/dev/null || true
  done < <(git -C "$root" ls-files -z --cached --others --exclude-standard -- \
    "packages/$name" "profiles" "scripts" ".rpmx-revision" | sort -z)

  memo[$name]=$(sha256sum "$inner" | cut -d' ' -f1)
  unset "visiting[$name]"
}

for name in "${names[@]}"; do
  hash_for "$name"
done

for name in "${names[@]}"; do
  printf '%s %s\n' "$name" "${memo[$name]}"
done
