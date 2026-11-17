#!/usr/bin/env bash
# Run installed and transaction tests against existing package artifacts.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}
rpm_directory="$root/out"
output="$root/out/tests"
arch=$(uname -m)
runner=auto
test_profile="$root/profiles/eternal.profile.yaml"
names=()
candidate_rpms=
build_release=
include_optional_tests=0

usage() {
  cat <<'EOF'
usage: test-all.sh [--package NAME...] [--rpms DIR] [--output DIR]
                   [--arch ARCH] [--runner RUNNER]
                   [--test-profile FILE] [--candidate-rpms DIR]
                   [--build-release N] [--include-optional-tests]

Run runtime tests without rebuilding. Input RPMs use DIR/NAME/ARCH/.
The default input is out/. Reports and logs go to out/tests/.
Missing artifacts, failed tests and skipped tests produce a nonzero exit.
Source suites run only during rpmx build, as build.tests.
--include-optional-tests also selects cases marked optional; failures remain fatal.
--candidate-rpms pools canonical DIR/NAME/ARCH/ binary outputs and their
build-policy.json receipts with the selected subjects, just like CI. Nested
fixtures, source RPMs and foreign architectures never enter the pool.
EOF
}

while (($#)); do
  case "$1" in
    --package) names+=("${2:?--package needs a name}"); shift 2 ;;
    --rpms) rpm_directory=${2:?--rpms needs a directory}; shift 2 ;;
    --output) output=${2:?--output needs a directory}; shift 2 ;;
    --arch) arch=${2:?--arch needs an architecture}; shift 2 ;;
    --runner) runner=${2:?--runner needs a runner}; shift 2 ;;
    --test-profile) test_profile=${2:?--test-profile needs a file}; shift 2 ;;
    --candidate-rpms) candidate_rpms=${2:?--candidate-rpms needs a directory}; shift 2 ;;
    --include-optional-tests) include_optional_tests=1; shift ;;
    --build-release) build_release=${2:?--build-release needs a value}; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$arch" in
  x86_64 | aarch64) ;;
  *) echo "unsupported architecture: $arch" >&2; exit 2 ;;
esac
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
if ((${#names[@]} == 0)); then
  for recipe in "$root"/packages/*/package.yaml; do
    names+=("$(basename "$(dirname "$recipe")")")
  done
fi
for name in "${names[@]}"; do
  [[ $name =~ ^[a-zA-Z0-9][a-zA-Z0-9.+_-]*$ && -f "$root/packages/$name/package.yaml" ]] || {
    echo "unknown package: $name" >&2; exit 2;
  }
done
mkdir -p "$output"
summary="$output/results.tsv"
printf 'package\tarch\tstatus\treport\n' >"$summary"
shopt -s nullglob
install_pool=
if [[ -n $candidate_rpms ]]; then
  [[ -d $candidate_rpms ]] || { echo "missing candidate outputs: $candidate_rpms" >&2; exit 1; }
  # Use the same transport and duplicate checks as CI. All pooled outputs
  # require the build receipt; never synthesize repository policy or metadata.
  scratch=$(mktemp -d)
  trap 'rm -rf "$scratch"' EXIT
  mkdir "$scratch/members"
  declare -A exported
  member_count=0
  sources=("$candidate_rpms"/*/"$arch")
  for name in "${names[@]}"; do
    [[ ! -d $rpm_directory/$name/$arch ]] || sources+=("$rpm_directory/$name/$arch")
  done
  for directory in "${sources[@]}"; do
    [[ -d $directory ]] || continue
    source=$(realpath "$directory")
    [[ -z ${exported[$source]:-} ]] || continue
    member="$scratch/members/$member_count"
    member_count=$((member_count + 1))
    python3 "$root/scripts/candidate-pool.py" export --source "$source" \
      --output "$member" --arch "$arch"
    exported[$source]=1
  done
  install_pool="$scratch/pool"
  python3 "$root/scripts/candidate-pool.py" assemble --source "$scratch/members" \
    --output "$install_pool" --arch "$arch"
fi
failed=0
shopt -s nullglob
for name in "${names[@]}"; do
  recipe="$root/packages/$name/package.yaml"
  directory="$rpm_directory/$name/$arch"
  reports="$output/$name/$arch"
  mkdir -p "$reports"
  rm -f "$reports/results.json" "$reports/junit.xml"
  echo "==> test $name ($arch)"
  effective_build_release=$build_release
  if [[ -z $effective_build_release && -f $directory/build-policy.json ]]; then
    effective_build_release=$(jq -er '.build_release // empty' "$directory/build-policy.json") || {
      # A null release is the ordinary recipe release, without a rolling suffix.
      jq -e '.build_release == null' "$directory/build-policy.json" >/dev/null || exit 1
      effective_build_release=
    }
  fi
  plan=("$rpmx" plan "$recipe" --arch "$arch" --json)
  [[ -z $effective_build_release ]] || plan+=(--build-release "$effective_build_release")
  if ! "${plan[@]}" >"$reports/plan.json" 2>"$reports/run.log"; then
    printf '%s\t%s\tinvalid\t%s\n' "$name" "$arch" "$reports/run.log" >>"$summary"
    cat "$reports/plan.json" "$reports/run.log" >&2
    failed=1
    continue
  fi
  expected=$(jq --argjson include_optional_tests "$include_optional_tests" \
    '[.plan.cells[].tests[] | select($include_optional_tests == 1 or .optional != true)] | length' \
    "$reports/plan.json")
  if ((expected == 0)); then
    echo "no installed-package tests selected: $name (use --include-optional-tests to select optional cases)" >&2
    printf '%s\t%s\tno-selected-tests\t%s\n' "$name" "$arch" "$reports/plan.json" >>"$summary"
    failed=1
    continue
  fi
  binaries=()
  for rpm in "$directory"/*.rpm; do
    [[ ! -L $rpm && ( $rpm == *."$arch".rpm || $rpm == *.noarch.rpm ) ]] && binaries+=("$rpm")
  done
  if ((${#binaries[@]} == 0)); then
    echo "missing binary RPMs: $directory" >&2
    printf '%s\t%s\tmissing\t%s\n' "$name" "$arch" "$reports/run.log" >>"$summary"
    failed=1
    continue
  fi
  sha256sum -- "${binaries[@]}" >"$reports/rpms.sha256"
  sha256sum -- "$(command -v "$rpmx")" >"$reports/rpmx.sha256"
  cp "$root/.rpmx-revision" "$reports/rpmx-revision"
  (
    cd "$root/packages/$name"
    find . -type f -print0 | sort -z | xargs -0 sha256sum
  ) >"$reports/recipe-inputs.sha256"
  command=(python3 "$root/scripts/accept-rpms.py" "$recipe" --arch "$arch" --runner "$runner"
    --test-profile "$test_profile" --install-dir "${install_pool:-$directory}" --output "$reports")
  [[ -z $effective_build_release ]] || command+=(--build-release "$effective_build_release")
  ((include_optional_tests == 0)) || command+=(--include-optional-tests)
  status=failed
  if RPMX="$rpmx" "${command[@]}"; then
    status=passed
  fi
  if [[ $status != passed ]]; then
    failed=1
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$arch" "$status" "$reports/results.json" >>"$summary"
done
echo "results: $summary"
exit "$failed"
