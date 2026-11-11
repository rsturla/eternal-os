#!/usr/bin/env bash
# Select the packages affected by a change.
#
# A package is affected when:
#   - a file under packages/<name>/ changed, or
#   - a profile, a build script or the repository defaults changed (all
#     packages), or
#
# A change to the pinned rpmx revision is not a recipe change: it swaps the
# builder, so it selects one canary package instead of every package. One
# end-to-end build proves the new revision still assembles roots and emits
# RPMs; the content hash still invalidates everything else on release.
#
# Regular builds consume published RPMs, not other recipes in this checkout.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
base=
all=0
json=0

usage() {
  cat <<'EOF'
usage: affected.sh [options]

  --base REF                   Compare against REF (default: origin/HEAD)
  --all                        Select every package
  --json                       Emit a JSON array
  -h, --help                   Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --base)
      base=${2:?--base needs a ref}
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

# The canary built when only the builder changed. Keep it cheap and
# self-contained: a shell pipeline over files shipped in the recipe, with no
# sources and no in-tree build dependencies, so the build cannot fail for a
# reason unrelated to rpmx.
canary=eternal-release

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
builder=0
while IFS= read -r -d '' path; do
  [[ -n $path ]] || continue
  case "$path" in
    scripts/affected.sh)
      # This file only decides which packages to select; changing it does not
      # change package output. The commit and lint checks still run.
      ;;
    profiles/* | scripts/* | rpmx-defaults.yaml)
      global=1
      break
      ;;
    .rpmx-revision)
      # The builder changed, not a recipe: a canary build is enough.
      builder=1
      ;;
    packages/openssf-compiler-options/*)
      # Every C/C++ build installs this package through the bootstrap profile.
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
  if ((builder)); then
    if [[ -z ${known[$canary]:-} ]]; then
      echo "canary package '$canary' does not exist" >&2
      exit 1
    fi
    emit "$canary"
  else
    emit
  fi
  exit 0
fi

emit "${!changed_package[@]}"
