#!/usr/bin/env bash
# Build selected foundation candidates before their consumers, locally or in CI.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
arch=
output=out
rpms=
packages=()
extra=()
usage() {
  echo 'usage: build-test-dependencies.sh --package NAME... --arch ARCH --output DIR --rpms DIR'
  echo 'Select kernel-headers, glibc-2.44, rpm, and/or openssl3. The candidate destination must be new.'
  echo 'Optional: --signing-key FILE --build-release N --jobs N --test-profile FILE --force --locked'
}
while (($#)); do
  case "$1" in
    --package) packages+=("${2:?--package needs a name}"); shift 2 ;;
    --arch) arch=${2:?--arch needs an architecture}; shift 2 ;;
    --output) output=${2:?--output needs a directory}; shift 2 ;;
    --rpms) rpms=${2:?--rpms needs a directory}; shift 2 ;;
    --signing-key|--build-release|--jobs|--test-profile)
      extra+=("$1" "${2:?option needs a value}"); shift 2 ;;
    --force|--locked) extra+=("$1"); shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -z $arch || $arch == all || -z $rpms || ${#packages[@]} == 0 ]]; then
  usage >&2
  exit 2
fi
declare -A selected=()
for name in "${packages[@]}"; do
  case "$name" in
    kernel-headers|glibc-2.44|rpm|openssl3) ;;
    *) echo "unsupported test foundation: $name" >&2; exit 2 ;;
  esac
  if [[ -v selected[$name] ]]; then
    echo "duplicate test foundation: $name" >&2
    exit 2
  fi
  selected[$name]=1
done
# Own this destination exclusively. Reusing a directory cannot supply an old
# successful candidate after a failed build in the current selection.
if [[ -e $rpms ]]; then
  echo "candidate RPM destination already exists: $rpms" >&2
  exit 2
fi
mkdir -p "$rpms"
rpms=$(realpath -e -- "$rpms")
for name in kernel-headers glibc-2.44 rpm openssl3; do
  [[ -v selected[$name] ]] || continue
  args=(--package "$name" --arch "$arch" --output "$output" "${extra[@]}")
  if find "$rpms" -type f -name '*.rpm' -print -quit | read -r _; then
    args+=(--test-rpms "$rpms")
  fi
  "$root/scripts/build-all.sh" "${args[@]}"
  found=0
  while IFS= read -r -d '' package; do
    cp -- "$package" "$rpms/"
    found=1
  done < <(find "$output/$name/$arch" -type f -name '*.rpm' ! -name '*.src.rpm' -print0)
  if ((found == 0)); then
    echo "successful foundation build produced no binary RPMs: $name" >&2
    exit 1
  fi
done
