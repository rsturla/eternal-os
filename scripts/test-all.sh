#!/usr/bin/env bash
# Run installed and transaction tests against existing package artifacts.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}
rpm_directory="$root/out"
output="$root/out/tests"
arch=$(uname -m)
runner=auto
root_lock=
test_profile="$root/profiles/eternal.profile.yaml"
names=()

usage() {
  cat <<'EOF'
usage: test-all.sh [--package NAME...] [--rpms DIR] [--output DIR]
                   [--arch ARCH] [--runner RUNNER] [--root-lock FILE]
                   [--test-profile FILE]

Run runtime tests without rebuilding. Input RPMs use DIR/NAME/ARCH/.
The default input is out/. Reports and logs go to out/tests/.
Missing artifacts, failed tests and skipped tests produce a nonzero exit.
Build-stage suites still require rpmx build or rpmx test without --install-dir.
EOF
}

while (($#)); do
  case "$1" in
    --package) names+=("${2:?--package needs a name}"); shift 2 ;;
    --rpms) rpm_directory=${2:?--rpms needs a directory}; shift 2 ;;
    --output) output=${2:?--output needs a directory}; shift 2 ;;
    --arch) arch=${2:?--arch needs an architecture}; shift 2 ;;
    --runner) runner=${2:?--runner needs a runner}; shift 2 ;;
    --root-lock) root_lock=${2:?--root-lock needs a file}; shift 2 ;;
    --test-profile) test_profile=${2:?--test-profile needs a file}; shift 2 ;;
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
failed=0
shopt -s nullglob
for name in "${names[@]}"; do
  recipe="$root/packages/$name/package.yaml"
  directory="$rpm_directory/$name/$arch"
  reports="$output/$name/$arch"
  mkdir -p "$reports"
  rm -f "$reports/results.json" "$reports/junit.xml"
  echo "==> test $name ($arch)"
  if ! "$rpmx" plan "$recipe" --arch "$arch" --json >"$reports/plan.json" 2>"$reports/run.log"; then
    printf '%s\t%s\tinvalid\t%s\n' "$name" "$arch" "$reports/run.log" >>"$summary"
    failed=1
    continue
  fi
  expected=$(jq '[.plan.cells[].tests[] | select(.stage != "build")] | length' "$reports/plan.json")
  if ((expected == 0)); then
    printf '%s\t%s\tbuild-only\t%s\n' "$name" "$arch" "$reports/plan.json" >>"$summary"
    failed=1
    continue
  fi
  binaries=()
  for rpm in "$directory"/*.rpm; do
    [[ $rpm == *.src.rpm ]] || binaries+=("$rpm")
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
  if [[ -z $root_lock ]]; then
    rm -f "$reports/input-root-lock.sha256"
  else
    sha256sum -- "$root_lock" >"$reports/input-root-lock.sha256"
  fi
  command=("$rpmx" test "$recipe" --arch "$arch" --runner "$runner"
    --test-profile "$test_profile"
    --install-dir "$directory" --junit "$reports/junit.xml"
    --test-output "$reports/artifacts" --json)
  [[ -z $root_lock ]] || command+=(--root-lock "$root_lock")
  status=failed
  if "${command[@]}" >"$reports/results.json" 2>>"$reports/run.log"; then
    if jq -e --argjson expected "$expected" '.ok == true and (.tests | length == $expected) and all(.tests[]; .status == "passed")' "$reports/results.json" >/dev/null; then
      status=passed
    else
      status=incomplete
    fi
  fi
  if [[ $status != passed ]]; then
    failed=1
    # Preparation errors live in the JSON response before any test log exists.
    jq -r '.diagnostics[]? | "\(.code): \(.message)"' "$reports/results.json" >&2 || :
    tail -n 15 "$reports/run.log" >&2
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$arch" "$status" "$reports/results.json" >>"$summary"
done
echo "results: $summary"
exit "$failed"
