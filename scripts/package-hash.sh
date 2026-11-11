#!/usr/bin/env bash
# Content hash for one or more packages.
#
# The hash covers local inputs to the package build:
#   - every tracked file under packages/<name>/ (recipe, includes, context);
#   - every profile, because a build-root change can affect any output;
#   - scripts/, because a change to the build entry points is a build change;
#   - the pinned rpmx revision and repository defaults.
#
# It is used for local stamps and CI cache keys. Published repository changes
# are not captured until the build root is pinned.
#
#   ./scripts/package-hash.sh                 # all packages, "name hash" lines
#   ./scripts/package-hash.sh foo bar         # selected packages
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
names=()

usage() {
  cat <<'EOF'
usage: package-hash.sh [NAME...]

  -h, --help    Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
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

if [[ -z ${names[*]-} ]]; then
  mapfile -t names < <("$root/scripts/list-packages.sh")
fi
for name in "${names[@]}"; do
  [[ -f "$root/packages/$name/package.yaml" ]] || {
    echo "unknown package: $name" >&2
    exit 1
  }
done

declare -A own
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

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

for name in "${names[@]}"; do
  own_hash_for "$name"
  printf '%s %s\n' "$name" "${own[$name]}"
done
