#!/usr/bin/env bash
# Build selected foundation candidates before their consumers, locally or in CI.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
arch=
output=out
rpms=
compiler_inputs=
cohort_extra=()
cohort_accept_extra=()
packages=()
extra=()
usage() {
  echo 'usage: build-test-dependencies.sh --package NAME... --arch ARCH --output DIR --rpms DIR'
  echo 'Select foundation packages and/or gcc-13 through gcc-16. The candidate destination must be new.'
  echo '--compiler-inputs DIR accepts existing quarantined compiler producers; otherwise produce them locally.'
  echo 'Optional: --signing-key FILE --build-release N --jobs N --test-profile FILE --force --locked'
}
while (($#)); do
  case "$1" in
    --package) packages+=("${2:?--package needs a name}"); shift 2 ;;
    --arch) arch=${2:?--arch needs an architecture}; shift 2 ;;
    --output) output=${2:?--output needs a directory}; shift 2 ;;
    --rpms) rpms=${2:?--rpms needs a directory}; shift 2 ;;
    --compiler-inputs) compiler_inputs=${2:?--compiler-inputs needs a directory}; shift 2 ;;
    --signing-key|--build-release|--jobs)
      extra+=("$1" "${2:?option needs a value}")
      cohort_extra+=("$1" "$2")
      [[ $1 != --build-release ]] || cohort_accept_extra+=("$1" "$2")
      shift 2 ;;
    --test-profile)
      extra+=("$1" "${2:?option needs a value}")
      test_profile=$2
      shift 2 ;;
    --force) extra+=("$1"); shift ;;
    --locked) extra+=("$1"); cohort_extra+=("$1"); shift ;;
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
    kernel-headers|glibc-2.44|rpm|openssl3|gcc-13|gcc-14|gcc-15|gcc-16|openssf-compiler-options) ;;
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
compilers=()
for name in gcc-13 gcc-14 gcc-15 gcc-16; do
  [[ ! -v selected[$name] ]] || compilers+=("$name")
done
if ((${#compilers[@]})); then
  if [[ -n ${test_profile:-} && $(realpath -e -- "$test_profile") != "$root/profiles/eternal.profile.yaml" ]]; then
    echo "compiler cohorts require the Eternal production test profile" >&2
    exit 2
  fi
  if [[ -z $compiler_inputs ]]; then
    compiler_inputs=$(mktemp -d "${TMPDIR:-/tmp}/eternal-compiler-producers.XXXXXXXX")
    echo "==> compiler producer quarantine $compiler_inputs" >&2
    python3 "$root/scripts/compiler-cohort.py" produce-seed --arch "$arch" \
      --output "$compiler_inputs/openssf-compiler-options" "${cohort_extra[@]}"
    for name in "${compilers[@]}"; do
      python3 "$root/scripts/compiler-cohort.py" produce --package "$name" --arch "$arch" \
        --seed "$compiler_inputs/openssf-compiler-options" --output "$compiler_inputs/$name" "${cohort_extra[@]}"
    done
  fi
  cohort=(python3 "$root/scripts/compiler-cohort.py" accept --arch "$arch" \
    --inputs "$compiler_inputs" --output "$output" --rpms "$rpms" "${cohort_accept_extra[@]}")
  for name in "${compilers[@]}"; do cohort+=(--package "$name"); done
  [[ ! -v selected[openssf-compiler-options] ]] || cohort+=(--package openssf-compiler-options)
  "${cohort[@]}"
elif [[ -n $compiler_inputs ]]; then
  echo "--compiler-inputs requires selected compiler streams" >&2
  exit 2
fi
for name in openssf-compiler-options kernel-headers glibc-2.44 rpm openssl3; do
  if [[ $name == openssf-compiler-options && ${#compilers[@]} != 0 ]]; then continue; fi
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
  done < <(find "$output/$name/$arch" -maxdepth 1 -type f -name '*.rpm' ! -name '*.src.rpm' -print0)
  if ((found == 0)); then
    echo "successful foundation build produced no binary RPMs: $name" >&2
    exit 1
  fi
done
