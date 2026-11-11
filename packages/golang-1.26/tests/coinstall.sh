#!/usr/bin/bash
set -euo pipefail
# shellcheck source=packages/golang-1.26/tests/environment.sh
source "$TEST_FILES/environment.sh" "$@"
test "$("$go" env GOROOT)" = "$LIBDIR/golang-${version%.*}"
test ! /usr/bin/go -ef "$LIBDIR/golang-${version%.*}/bin/go"
CGO_ENABLED=0 "$go" build -o eternal-consumer "$TEST_FILES/hello.go"
CGO_ENABLED=0 /usr/bin/go build -o fedora-consumer "$TEST_FILES/hello.go"
test "$(./eternal-consumer)" = go-ok
test "$(./fedora-consumer)" = go-ok
