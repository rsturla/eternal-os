#!/usr/bin/bash
set -euo pipefail
# shellcheck source=packages/golang-1.26/tests/environment.sh
source "$TEST_FILES/environment.sh" "$@"
export CGO_ENABLED=0
test "$("$go" env GOROOT)" = "$LIBDIR/golang-${version%.*}"
cp -a "$TEST_FILES/module" module
cd module
"$go" test -count=1 -v ./... >../unit-tests.log
for name in TestAlgorithms TestCompressionErrors TestFilesystem TestConcurrency; do
    grep -F -- "--- PASS: $name " ../unit-tests.log
done
"$go" vet ./...
"$go" build -trimpath -o ../consumer ./cmd/consumer
cd ..
test "$(./consumer)" = 'answer=42 sorted=[1 2 3]'
cp "$TEST_FILES/format.input" formatting.go
"$gofmt" -w formatting.go
cmp formatting.go "$TEST_FILES/format.expected"
test -z "$("$gofmt" -l formatting.go)"
if "$go" build -o invalid "$TEST_FILES/invalid.go" >invalid.stdout 2>invalid.stderr; then
    echo 'compiler accepted an undefined identifier' >&2; exit 1
fi
case "$(<invalid.stderr)" in
    *'undefined: missing_identifier'*) ;;
    *) echo 'compiler failed without the expected identifier diagnostic' >&2; cat invalid.stderr >&2; exit 1 ;;
esac
test ! -e invalid
if "$go" vet "$TEST_FILES/vet-invalid.go" >vet.stdout 2>vet.stderr; then
    echo 'go vet accepted a mismatched Printf argument' >&2; exit 1
fi
case "$(<vet.stderr)" in
    *'fmt.Printf format %d'*'wrong type string'*) ;;
    *) echo 'go vet failed without the expected format diagnostic' >&2; cat vet.stderr >&2; exit 1 ;;
esac
