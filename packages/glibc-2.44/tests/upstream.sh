#!/usr/bin/env bash
# Keep individual failure diagnostics even when make check exits immediately.
set -euo pipefail

collect_failure_evidence() {
  mkdir -p upstream-reports || return
  [[ -f build/tests.sum ]] || return 0
  cp build/tests.sum upstream-reports/ || return
  while IFS= read -r line; do
    case "$line" in
      FAIL:*|XPASS:*|ERROR:*|UNRESOLVED:*) ;;
      *) continue ;;
    esac
    name=${line#*: }
    if [[ ! $name =~ ^[a-zA-Z0-9_+./-]+$ || $name == /* || $name == *..* ]]; then
      printf 'invalid upstream test result path: %s\n' "$name" >&2
      return 1
    fi
    for suffix in .out .test-result -out; do
      path="build/$name$suffix"
      [[ -f $path ]] || continue
      cp --parents -- "$path" upstream-reports/ || return
      printf 'upstream failure diagnostic: %s\n' "$path" >&2
      cat -- "$path" >&2 || return
    done
  done < build/tests.sum
}

finish() {
  status=$?
  trap - EXIT
  if ! collect_failure_evidence; then
    echo 'cannot retain upstream failure diagnostics' >&2
    ((status != 0)) || status=1
  fi
  exit "$status"
}
trap finish EXIT

make -C build -j2 check
test -s build/tests.sum
grep '^PASS:' build/tests.sum
if grep -E '^(FAIL|XPASS|ERROR|UNRESOLVED):' build/tests.sum; then
  echo 'unexpected glibc upstream test result' >&2
  exit 1
fi
