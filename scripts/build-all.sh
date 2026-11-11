#!/usr/bin/env bash
# Build packages, incrementally.
#
# By default every package is considered, but a package whose content hash
# matches its stamp is skipped. Use --affected to consider only packages
# touched by a diff, and --all --force to rebuild everything.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}
original_args=("$@")

package=
selection=all
since=
output=out
arch=
signing_key=
build_release=
jobs=
force=0
locked=0
no_tests=0
test_profile="$root/profiles/eternal.profile.yaml"
test_rpms=
extra=()

usage() {
  cat <<'EOF'
usage: build-all.sh [options]

  --package NAME     Build packages/NAME only
  --affected         Build only packages affected by a diff
  --since REF        Base ref for --affected (default: origin/HEAD)
  --all              Consider every package (the default)
  --force            Rebuild even when the content hash matches
  --output DIR       Artifacts root; recipes write DIR/<name>/<arch>
  --arch ARCH        Target architecture (default: rpmx default)
  --signing-key FILE Sign RPMs with this OpenPGP secret key
  --build-release N  Append +buildN to rebuilt packages (rolling releases)
  --jobs N           Parallel build jobs exported to steps as JOBS
  --locked           Refuse recipe, source or root drift
  --no-tests         Skip source suites and package acceptance
  --test-profile FILE Repository policy for runtime tests (default: Eternal)
  --test-rpms DIR    Prefer these candidate binary RPMs in isolated test roots
  -h, --help         Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --package | -p)
      package=${2:?--package needs a name}
      shift 2
      ;;
    --affected)
      selection=affected
      shift
      ;;
    --since)
      since=${2:?--since needs a ref}
      selection=affected
      shift 2
      ;;
    --all)
      selection=all
      shift
      ;;
    --force)
      force=1
      shift
      ;;
    --output | -o)
      output=${2:?--output needs a directory}
      shift 2
      ;;
    --arch)
      arch=${2:?--arch needs an architecture}
      shift 2
      ;;
    --signing-key)
      signing_key=${2:?--signing-key needs a file}
      shift 2
      ;;
    --build-release)
      build_release=${2:?--build-release needs a number}
      shift 2
      ;;
    --jobs)
      jobs=${2:?--jobs needs a number}
      shift 2
      ;;
    --locked)
      locked=1
      extra+=(--locked)
      shift
      ;;
    --no-tests)
      no_tests=1
      extra+=(--no-tests)
      shift
      ;;
    --test-profile)
      test_profile=${2:?--test-profile needs a file}
      shift 2
      ;;
    --test-rpms)
      test_rpms=${2:?--test-rpms needs a directory}
      shift 2
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

if [[ -n $test_rpms ]] && ((no_tests)); then
  echo "--test-rpms cannot be combined with --no-tests" >&2
  exit 2
fi

if [[ -n $package && $selection == affected ]]; then
  echo "--package cannot be combined with --affected" >&2
  exit 2
fi

# Run the same
# entry point once per declared architecture, retaining each report and failure.
if [[ $arch == all ]]; then
  declared_arches=$(python3 - "$root/profiles/bootstrap.profile.yaml" <<'PY'
import sys
import yaml
with open(sys.argv[1]) as source:
    arches = yaml.safe_load(source)["archs"]
if not arches or any(not isinstance(arch, str) or arch == "all" for arch in arches):
    raise SystemExit("bootstrap profile must declare concrete architectures")
print("\n".join(arches))
PY
  )
  mapfile -t target_arches <<<"$declared_arches"
  status=0
  for target_arch in "${target_arches[@]}"; do
    arch_args=()
    for ((index = 0; index < ${#original_args[@]}; index++)); do
      if [[ ${original_args[index]} == --arch ]]; then
        arch_args+=(--arch "$target_arch")
        index=$((index + 1))
      else
        arch_args+=("${original_args[index]}")
      fi
    done
    if "$root/scripts/build-all.sh" "${arch_args[@]}"; then
      :
    else
      failed=$?
      ((status != 0)) || status=$failed
    fi
  done
  exit "$status"
fi

# Relative repository and key paths are anchored at the profile location.
# Include that location as well as its contents in cached test outcomes.
if [[ -n $test_rpms ]]; then
  test_rpms=$(realpath -e -- "$test_rpms")
  candidate_identity=$(
    { printf '%s\0' "$(realpath -e -- "$test_profile")"; cat -- "$test_profile"
      find "$test_rpms" -type f -name '*.rpm' -print0 | sort -z | xargs -0 -r sha256sum
    } | sha256sum | cut -d' ' -f1
  )
  candidate_profile="$root/.work/test-profiles/${arch:-$(uname -m)}/$candidate_identity/profile.yaml"
  RPMX="$rpmx" python3 "$root/scripts/prepare-test-profile.py" \
    --profile "$test_profile" --rpms "$test_rpms" \
    --arch "${arch:-$(uname -m)}" --output "$candidate_profile"
  test_profile=$candidate_profile
fi
test_profile_identity=disabled
if ((no_tests == 0)); then
  test_profile=$(realpath -e -- "$test_profile")
  test_profile_identity=$({ printf '%s\0' "$test_profile"; cat -- "$test_profile"; } | sha256sum | cut -d' ' -f1)
fi
test_variant="tests=$((1 - no_tests)) test-profile=$test_profile_identity"

# rpmx already retains raw logs beside built RPMs. Publish private seed logs
# under the same output tree as normal package reports, including on failure.
test_junit_path() {
  printf '%s/%s/junit.xml' "$1" "${arch:-$(uname -m)}"
}

collect_test_evidence() {
  local build_output=$1 reports=$2 directory target junit collected=0
  junit=$(test_junit_path "$build_output")
  local -a directories=("$build_output/${arch:-$(uname -m)}/test-results" "$build_output/${arch:-$(uname -m)}/acceptance" "$build_output/${arch:-$(uname -m)}/build")
  if [[ -f $junit ]]; then
    mkdir -p "$reports" || return
    cp -- "$junit" "$reports/junit.xml" || return
    collected=1
  fi
  for directory in "${directories[@]}"; do
    [[ -d $directory ]] || continue
    target="$reports/$(basename "$(dirname "$directory")")"
    mkdir -p "$target" || return
    cp -a -- "$directory" "$target/" || return
    collected=1
  done
  if ((collected)); then
    echo "==> test evidence $reports" >&2
  fi
}

run_build() {
  local build_output=$1 reports=$2 status=0
  shift 2
  if ((no_tests == 0)); then
    # Clear test evidence only. Retain package outputs and other architectures.
    # A build that fails before tests must not publish older successful tests.
    rm -f -- "$(test_junit_path "$build_output")" "$build_output/run-report.json" "$build_output/run-report.xml"
    mkdir -p "$(dirname "$(test_junit_path "$build_output")")"
    if [[ -n $reports ]]; then
      rm -rf -- "$reports"
      mkdir -p "$reports"
    fi
    rm -rf -- "$build_output/${arch:-$(uname -m)}/test-results" "$build_output/${arch:-$(uname -m)}/acceptance" "$build_output/${arch:-$(uname -m)}/build"
  fi
  "$@" || status=$?
  if ((status == 0 && no_tests == 0)); then
    if ! jq -e '.document == "rpmx-run-report" and .version == 1 and .outcome == "passed" and .build_tests_requested == true and all(.build_tests[]; .status == "passed")' "$build_output/run-report.json" >/dev/null; then
      echo "build did not produce complete passing source evidence: $build_output/run-report.json" >&2
      status=1
    fi
  fi
  if ((status == 0 && no_tests == 0)); then
    local recipe
    recipe=$3
    local -a acceptance=(python3 "$root/scripts/accept-rpms.py" "$recipe"
      --install-dir "$build_output/${arch:-$(uname -m)}"
      --output "$build_output/${arch:-$(uname -m)}/acceptance"
      --arch "${arch:-$(uname -m)}" --test-profile "$test_profile")
    local argument previous='' effective_build_release=''
    for argument in "$@"; do
      [[ $previous != --build-release ]] || effective_build_release=$argument
      previous=$argument
    done
    [[ -z $effective_build_release ]] || acceptance+=(--build-release "$effective_build_release")
    RPMX="$rpmx" "${acceptance[@]}" || status=$?
  fi
  if ((no_tests == 0)); then
    [[ ! -f $build_output/run-report.xml ]] || cp -- "$build_output/run-report.xml" "$(test_junit_path "$build_output")"
    if [[ -f $build_output/run-report.json ]]; then
      local source_reports="$build_output/${arch:-$(uname -m)}/build"
      mkdir -p "$source_reports"
      cp -- "$build_output/run-report.json" "$source_reports/"
      [[ ! -f $build_output/run-report.xml ]] || cp -- "$build_output/run-report.xml" "$source_reports/"
      while IFS= read -r evidence; do
        [[ -e $evidence ]] || continue
        local relative
        relative=$(realpath --relative-to="$build_output" -- "$evidence")
        if [[ $relative == ../* || $relative == .. ]]; then
          echo "build evidence escapes output: $evidence" >&2
          ((status != 0)) || status=1
          continue
        fi
        mkdir -p "$source_reports/evidence"
        local destination
        destination=$(realpath -- "$source_reports/evidence")
        (cd "$build_output" && cp -a --parents -- "$relative" "$destination/") || { ((status != 0)) || status=1; }
      done < <(jq -r '.evidence[]' "$build_output/run-report.json")
    fi
    if [[ -z $reports ]]; then
      echo "==> test evidence $build_output" >&2
    elif ! collect_test_evidence "$build_output" "$reports"; then
      echo "cannot collect test evidence in $reports" >&2
      ((status != 0)) || status=1
    fi
  fi
  return "$status"
}

# The bootstrap profiles install openssf-compiler-options from this local
# repository. Build it first with bootstrap-toolchain.profile.yaml, which is the
# one profile that does not install the package it is building.
toolchain_repo="$root/.work/toolchain-repo"
toolchain_out="$root/.work/toolchain-out"
toolchain_rpms="$root/.work/toolchain-rpms"

ensure_toolchain_repo() {
  local hash stamp seed_identity reports report_identity
  hash=$("$root/scripts/package-hash.sh" openssf-compiler-options | awk '{print $2}')
  stamp="$toolchain_repo/.stamp"
  seed_identity="$hash arch=${arch:-$(uname -m)} $test_variant"
  report_identity=$(printf '%s' "$seed_identity" | sha256sum | cut -d' ' -f1)
  reports="$output/test-reports/toolchain/$report_identity"
  if [[ -f $stamp && -f $toolchain_repo/repodata/repomd.xml ]] &&
     [[ $(<"$stamp") == "$seed_identity" ]]; then
    if ((no_tests == 0)) && ! collect_test_evidence "$toolchain_out" "$reports"; then
      echo "cannot collect test evidence in $reports" >&2
      return 1
    fi
    return 0
  fi

  rm -rf "$toolchain_out" "$toolchain_rpms" "$toolchain_repo"
  mkdir -p "$toolchain_out" "$toolchain_rpms"
  echo "==> build toolchain package openssf-compiler-options (${hash:0:12})"
  local -a args=("$rpmx" build "$root/packages/openssf-compiler-options/package.yaml"     --output "$toolchain_out")
  [[ -n $arch ]] && args+=(--arch "$arch")
  [[ -n $jobs ]] && args+=(--jobs "$jobs")
  ((no_tests)) && args+=(--no-tests)
  run_build "$toolchain_out" "$reports" "${args[@]}"

  find "$toolchain_out" -type f -name '*.rpm' ! -name '*.src.rpm' \
    -exec cp -t "$toolchain_rpms" {} +
  "$rpmx" repo --rpms "$toolchain_rpms" --output "$toolchain_repo"
  printf '%s\n' "$seed_identity" >"$stamp"
}

if [[ $package != openssf-compiler-options ]]; then
  ensure_toolchain_repo
fi

recipes=()
if [[ -n $package ]]; then
  recipe="$root/packages/$package/package.yaml"
  if [[ ! -f $recipe ]]; then
    echo "no recipe for package '$package' at ${recipe#"$root"/}" >&2
    exit 1
  fi
  recipes+=("$recipe")
elif [[ $selection == affected ]]; then
  affected_args=(--base "${since:-origin/HEAD}")
  while IFS= read -r name; do
    [[ -n $name ]] || continue
    recipes+=("$root/packages/$name/package.yaml")
  done < <("$root/scripts/affected.sh" "${affected_args[@]}")
else
  while IFS= read -r name; do
    [[ -n $name ]] || continue
    recipes+=("$root/packages/$name/package.yaml")
  done < <("$root/scripts/list-packages.sh")
fi

if [[ -z ${recipes[*]-} ]]; then
  echo "no packages selected" >&2
  exit 0
fi

names=()
for recipe in "${recipes[@]}"; do
  names+=("$(basename "$(dirname "$recipe")")")
done

# One hashing pass for the whole selection.
mapfile -t hashes < <("$root/scripts/package-hash.sh" "${names[@]}")
declare -A hash_of
for line in "${hashes[@]}"; do
  hash_of[${line%% *}]=${line##* }
done

stamp_dir="$output/.stamps/${arch:-native}"
variant="$test_variant signed=$([[ -n $signing_key ]] && echo 1 || echo 0) locked=$locked"

for recipe in "${recipes[@]}"; do
  name=$(basename "$(dirname "$recipe")")
  pkg_output="$output/$name"
  stamp="$stamp_dir/$name"
  # One output directory per package: the acceptance root must not
  # see RPMs from unrelated packages.
  cmd=("$rpmx" build "$recipe" --output "$pkg_output")
  [[ -n $arch ]] && cmd+=(--arch "$arch")
  [[ -n $signing_key ]] && cmd+=(--signing-key "$signing_key")
  [[ -n $build_release ]] && cmd+=(--build-release "$build_release")
  [[ -n $jobs ]] && cmd+=(--jobs "$jobs")
  cmd+=("${extra[@]}")

  stamp_hash=${hash_of[$name]:-missing}
  stamp_value="$stamp_hash $variant"

  if ((!force)) && [[ -f $stamp ]] && [[ $(cat "$stamp") == "$stamp_value" ]]; then
    if [[ -n $arch ]]; then
      pattern="$pkg_output/$arch/*.rpm"
    else
      pattern="$pkg_output/*/*.rpm"
    fi
    if compgen -G "$pattern" >/dev/null; then
      echo "==> skip $name (unchanged: ${stamp_hash:0:12})"
      ((no_tests)) || echo "==> test evidence $pkg_output" >&2
      continue
    fi
  fi

  echo "==> build ${recipe#"$root"/} (${stamp_hash:0:12}) -> $pkg_output"
  # A failed forced rebuild must not leave an earlier successful stamp.
  rm -f -- "$stamp"
  run_build "$pkg_output" "" "${cmd[@]}"

  mkdir -p "$stamp_dir"
  printf '%s\n' "$stamp_value" >"$stamp"
done
