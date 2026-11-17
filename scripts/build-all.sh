#!/usr/bin/env bash
# Build packages, incrementally.
#
# By default every package is considered, but a package whose content hash
# matches its stamp is skipped. Use --affected to consider only packages
# touched by a diff, and --all --force to rebuild everything.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}

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
defer_acceptance=0
extra=()

usage() {
  cat <<'EOF'
usage: build-all.sh [options]

  --package NAME     Build packages/NAME only
  --affected         Build only packages affected by a diff
  --since REF        Base ref for --affected (default: origin/HEAD)
  --all              Consider every package (the default)
  --force            Rebuild even when the content hash matches
  --output DIR       Artifacts root; each architecture writes DIR/<arch>
  --arch ARCH        Target architecture (default: rpmx default)
  --signing-key FILE Sign RPMs with this OpenPGP secret key
  --build-release N  Append +buildN to rebuilt packages (rolling releases)
  --jobs N           Parallel build jobs exported to steps as JOBS
  --locked           Refuse recipe, source or root drift
  --defer-acceptance Run source tests; accept the resulting RPMs separately
  --no-tests         Build without running the recipe's tests
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
    --defer-acceptance)
      defer_acceptance=1
      shift
      ;;
    --no-tests)
      no_tests=1
      extra+=(--no-tests)
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

if ((defer_acceptance && no_tests)); then
  echo "--defer-acceptance requires source tests; cannot combine with --no-tests" >&2
  exit 2
fi

if [[ -n $package && $selection == affected ]]; then
  echo "--package cannot be combined with --affected" >&2
  exit 2
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
variant="tests=$((1 - no_tests)) signed=$([[ -n $signing_key ]] && echo 1 || echo 0) locked=$locked deferred=$defer_acceptance"

for recipe in "${recipes[@]}"; do
  name=$(basename "$(dirname "$recipe")")
  pkg_output="$output/$name"
  stamp="$stamp_dir/$name"
  stamp_value="${hash_of[$name]:-missing} $variant"

  if ((!force)) && [[ -f $stamp ]] && [[ $(cat "$stamp") == "$stamp_value" ]]; then
    if [[ -n $arch ]]; then
      pattern="$pkg_output/$arch/*.rpm"
    else
      pattern="$pkg_output/*/*.rpm"
    fi
    if compgen -G "$pattern" >/dev/null; then
      echo "==> skip $name (unchanged: ${hash_of[$name]:0:12})"
      continue
    fi
  fi

  # Keep each package's source artifacts and acceptance evidence together.
  cmd=("$rpmx" build "$recipe" --output "$pkg_output")
  [[ -n $arch ]] && cmd+=(--arch "$arch")
  [[ -n $signing_key ]] && cmd+=(--signing-key "$signing_key")
  [[ -n $build_release ]] && cmd+=(--build-release "$build_release")
  [[ -n $jobs ]] && cmd+=(--jobs "$jobs")
  cmd+=("${extra[@]}")

  echo "==> build ${recipe#"$root"/} (${hash_of[$name]:0:12}) -> $pkg_output"
  # A failed rebuild must not leave an earlier success stamp or acceptance
  # receipt that can be mistaken for this invocation's result.
  rm -f -- "$stamp"
  rm -rf -- "$pkg_output/acceptance"
  "${cmd[@]}"

  # Persist the release that actually produced these bytes, including on cache hits.
  python3 - "$pkg_output/run-report.json" "$build_release" <<'PY_POLICY'
import json
from pathlib import Path
import sys
report = json.loads(Path(sys.argv[1]).read_text())
for directory in {Path(path).parent for path in report["artifacts"]["rpms"]}:
    (directory / "build-policy.json").write_text(json.dumps({"build_release": sys.argv[2] or None}) + "\n")
PY_POLICY

  if ((no_tests == 0 && defer_acceptance == 0)); then
    # The build report identifies this invocation's actual architecture outputs,
    # including --arch all. Do not test stale directories from earlier builds.
    mapfile -t built_arches < <(python3 - "$pkg_output/run-report.json" <<'PY_REPORT'
import json
from pathlib import Path
import sys
report = json.loads(Path(sys.argv[1]).read_text())
for arch in sorted({Path(path).parent.name for path in report["artifacts"]["rpms"]}):
    print(arch)
PY_REPORT
)
    if ((${#built_arches[@]} == 0)); then
      echo "successful build produced no reported binary RPMs: $name" >&2
      exit 1
    fi
    for target in "${built_arches[@]}"; do
      accept=(python3 "$root/scripts/accept-rpms.py" "$recipe"
        --arch "$target" --install-dir "$pkg_output/$target"
        --output "$pkg_output/acceptance/$target")
      [[ -z $build_release ]] || accept+=(--build-release "$build_release")
      "${accept[@]}"
    done
  fi

  mkdir -p "$stamp_dir"
  printf '%s\n' "$stamp_value" >"$stamp"
done
