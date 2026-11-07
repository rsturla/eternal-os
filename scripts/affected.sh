#!/usr/bin/env bash
# Select the packages affected by a change.
#
# A package is affected when:
#   - a file under packages/<name>/ changed, or
#   - a profile, a build script or the pinned rpmx revision changed (all
#     packages), or
#   - one of its in-tree build dependencies is affected (transitively).
#
# Runtime dependents are not rebuilt by default: their NEVRA does not embed the
# dependency. Use --with-runtime-dependents when a change also breaks the ABI
# they consume.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
base=
all=0
json=0
runtime=0
graph_file=

usage() {
  cat <<'EOF'
usage: affected.sh [options]

  --base REF                   Compare against REF (default: origin/HEAD)
  --graph FILE                 Reuse a graph produced by package-graph.sh
  --all                        Select every package
  --json                       Emit a JSON array
  --with-runtime-dependents    Also follow runtime edges
  -h, --help                   Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --base)
      base=${2:?--base needs a ref}
      shift 2
      ;;
    --graph)
      graph_file=${2:?--graph needs a file}
      shift 2
      ;;
    --all)
      all=1
      shift
      ;;
    --json)
      json=1
      shift
      ;;
    --with-runtime-dependents)
      runtime=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mapfile -t names < <("$root/scripts/list-packages.sh")
declare -A known
for name in "${names[@]}"; do
  known[$name]=1
done

emit() {
  if (($# == 0)); then
    ((json)) && echo '[]'
    return 0
  fi
  if ((json)); then
    printf '%s\n' "$@" | sort -u | jq -R -s -c 'split("\n") | map(select(length > 0))'
  else
    printf '%s\n' "$@" | sort -u
  fi
}

if ((all)); then
  emit "${names[@]}"
  exit 0
fi

if [[ -z $base ]]; then
  for candidate in origin/HEAD origin/main main; do
    if git -C "$root" rev-parse --verify --quiet "$candidate" >/dev/null; then
      base=$candidate
      break
    fi
  done
fi

if [[ -z $base ]]; then
  echo "no base ref found; selecting every package" >&2
  emit "${names[@]}"
  exit 0
fi

merge_base=$(git -C "$root" merge-base "$base" HEAD 2>/dev/null || true)
if [[ -z $merge_base ]]; then
  echo "cannot find a merge base for '$base'; selecting every package" >&2
  emit "${names[@]}"
  exit 0
fi

changed=$(mktemp)
trap 'rm -f "$changed"' EXIT

{
  git -C "$root" diff --name-only -z "$merge_base"...HEAD
  git -C "$root" diff --name-only -z HEAD
  git -C "$root" ls-files -z --others --exclude-standard
} >"$changed"

declare -A changed_package
changed_count=0
global=0
while IFS= read -r -d '' path; do
  [[ -n $path ]] || continue
  case "$path" in
    profiles/* | scripts/* | .rpmx-revision)
      global=1
      break
      ;;
    packages/*/*)
      rest=${path#packages/}
      name=${rest%%/*}
      [[ -n ${known[$name]:-} ]] && { changed_package[$name]=1; changed_count=$((changed_count + 1)); }
      ;;
  esac
done <"$changed"

if ((global)); then
  emit "${names[@]}"
  exit 0
fi

if ((changed_count == 0)); then
  emit
  exit 0
fi

graph=$(mktemp)
trap 'rm -f "$changed" "$graph"' EXIT
if [[ -n $graph_file ]]; then
  cp "$graph_file" "$graph"
else
  "$root/scripts/package-graph.sh" >"$graph"
fi

edge=build
((runtime)) && edge=both

declare -A reverse
while IFS=$'\t' read -r dependency dependent; do
  reverse[$dependency]+=" $dependent"
done < <(jq -r --arg edge "$edge" '
  to_entries[]
  | .key as $package
  | ((if $edge == "both" then (.value.build + .value.run) else .value.build end) | unique)[]
  | "\(.)\t\($package)"
' "$graph")

declare -A affected
queue=()
for name in "${!changed_package[@]}"; do
  affected[$name]=1
  queue+=("$name")
done

i=0
while ((i < ${#queue[@]})); do
  name=${queue[$i]}
  i=$((i + 1))
  for dependent in ${reverse[$name]:-}; do
    if [[ -z ${affected[$dependent]:-} ]]; then
      affected[$dependent]=1
      queue+=("$dependent")
    fi
  done
done

emit "${!affected[@]}"
