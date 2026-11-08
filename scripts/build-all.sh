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
extra=()

usage() {
  cat <<'EOF'
usage: build-all.sh [options]

  --package NAME     Build packages/NAME only
  --affected         Build only packages affected by a diff (plus build dependents)
  --since REF        Base ref for --affected (default: origin/HEAD)
  --all              Consider every package (the default)
  --force            Rebuild even when the content hash matches
  --output DIR       Artifacts root; each architecture writes DIR/<arch>
  --arch ARCH        Target architecture (default: rpmx default)
  --signing-key FILE Sign RPMs with this OpenPGP secret key
  --build-release N  Append +buildN to rebuilt packages (rolling releases)
  --jobs N           Parallel build jobs exported to steps as JOBS
  --locked           Refuse recipe, source or root drift
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

if [[ -n $package && $selection == affected ]]; then
  echo "--package cannot be combined with --affected" >&2
  exit 2
fi

# The bootstrap profiles install openssf-compiler-options from this local
# repository. Build it first with bootstrap-toolchain.profile.yaml, which is the
# one profile that does not install the package it is building.
toolchain_repo="$root/.work/toolchain-repo"
toolchain_out="$root/.work/toolchain-out"
toolchain_rpms="$root/.work/toolchain-rpms"

ensure_toolchain_repo() {
  local hash stamp
  hash=$("$root/scripts/package-hash.sh" openssf-compiler-options | awk '{print $2}')
  stamp="$toolchain_repo/.stamp"
  if [[ -f $stamp && -f $toolchain_repo/repodata/repomd.xml ]] &&
     [[ $(<"$stamp") == "$hash" ]]; then
    return 0
  fi

  rm -rf "$toolchain_out" "$toolchain_rpms" "$toolchain_repo"
  mkdir -p "$toolchain_out" "$toolchain_rpms"
  echo "==> build toolchain package openssf-compiler-options (${hash:0:12})"
  local -a args=("$rpmx" build "$root/packages/openssf-compiler-options/package.yaml"     --output "$toolchain_out")
  [[ -n $arch ]] && args+=(--arch "$arch")
  [[ -n $jobs ]] && args+=(--jobs "$jobs")
  ((no_tests)) && args+=(--no-tests)
  "${args[@]}"

  find "$toolchain_out" -type f -name '*.rpm' ! -name '*.src.rpm' \
    -exec cp -t "$toolchain_rpms" {} +
  "$rpmx" repo --rpms "$toolchain_rpms" --output "$toolchain_repo"
  printf '%s\n' "$hash" >"$stamp"
}

if [[ $package != openssf-compiler-options ]]; then
  ensure_toolchain_repo
fi

recipes=()
graph_file=$(mktemp)
trap 'rm -f "$graph_file"' EXIT
"$root/scripts/package-graph.sh" >"$graph_file"
if [[ -n $package ]]; then
  recipe="$root/packages/$package/package.yaml"
  if [[ ! -f $recipe ]]; then
    echo "no recipe for package '$package' at ${recipe#"$root"/}" >&2
    exit 1
  fi
  recipes+=("$recipe")
elif [[ $selection == affected ]]; then
  affected_args=(--graph "$graph_file" --base "${since:-origin/HEAD}")
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

# One graph and one hashing pass for the whole selection.
mapfile -t hashes < <("$root/scripts/package-hash.sh" --graph "$graph_file" "${names[@]}")
declare -A hash_of
for line in "${hashes[@]}"; do
  hash_of[${line%% *}]=${line##* }
done

stamp_dir="$output/.stamps/${arch:-native}"
variant="tests=$((1 - no_tests)) signed=$([[ -n $signing_key ]] && echo 1 || echo 0) locked=$locked"

for recipe in "${recipes[@]}"; do
  name=$(basename "$(dirname "$recipe")")
  pkg_output="$output/$name"
  stamp="$stamp_dir/$name"
  stamp_value="${hash_of[$name]:-missing} $variant"

  if ((!force)) && [[ -f $stamp ]] && [[ $(cat "$stamp") == "$stamp_value" ]]; then
    if [[ -n $arch ]]; then
      pattern="$pkg_output/$arch/${name}-*.rpm"
    else
      pattern="$pkg_output/*/${name}-*.rpm"
    fi
    if compgen -G "$pattern" >/dev/null; then
      echo "==> skip $name (unchanged: ${hash_of[$name]:0:12})"
      continue
    fi
  fi

  # One output directory per package: the installed-stage test root must not
  # see RPMs from unrelated packages.
  cmd=("$rpmx" build "$recipe" --output "$pkg_output")
  [[ -n $arch ]] && cmd+=(--arch "$arch")
  [[ -n $signing_key ]] && cmd+=(--signing-key "$signing_key")
  [[ -n $build_release ]] && cmd+=(--build-release "$build_release")
  [[ -n $jobs ]] && cmd+=(--jobs "$jobs")
  cmd+=("${extra[@]}")

  echo "==> build ${recipe#"$root"/} (${hash_of[$name]:0:12}) -> $pkg_output"
  "${cmd[@]}"

  mkdir -p "$stamp_dir"
  printf '%s\n' "$stamp_value" >"$stamp"
done
