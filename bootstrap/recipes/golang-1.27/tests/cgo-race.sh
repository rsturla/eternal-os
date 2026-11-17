#!/usr/bin/bash
set -euo pipefail
# shellcheck source=packages/golang-1.27/tests/environment.sh
source "$TEST_FILES/environment.sh" "$@"
export CGO_ENABLED=1 CC=gcc
"$go" build -buildmode=pie -o cgo-consumer "$TEST_FILES/cgo.go"
test "$(./cgo-consumer)" = 'cgo=42'
cp -a "$TEST_FILES/module" module
(cd module; "$go" test -race -count=1 -v ./...) >race-clean.log
for name in TestAlgorithms TestCompressionErrors TestFilesystem TestConcurrency; do
    grep -F -- "--- PASS: $name " race-clean.log
done
"$go" build -race -o race-invalid "$TEST_FILES/race-invalid.go"
status=0
GORACE='exitcode=66 halt_on_error=1 atexit_sleep_ms=0' ./race-invalid >race.stdout 2>race.stderr || status=$?
test "$status" = 66
grep -F 'WARNING: DATA RACE' race.stderr
# Cross-compilation is pure Go; no foreign GCC or foreign runtime is needed.
for arch in arm64 amd64; do
    CGO_ENABLED=0 GOARCH="$arch" "$go" build -o "consumer-$arch" "$TEST_FILES/hello.go"
    "$go" version -m "consumer-$arch" >"metadata-$arch.txt"
    grep -Fx $'\tbuild\tGOARCH='"$arch" "metadata-$arch.txt"
done
grep -Fx $'\tbuild\tGOARM64=v8.0' metadata-arm64.txt
grep -Fx $'\tbuild\tGOAMD64=v2' metadata-amd64.txt
