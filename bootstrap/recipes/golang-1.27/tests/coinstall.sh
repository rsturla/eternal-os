#!/usr/bin/bash
set -euo pipefail
# shellcheck source=packages/golang-1.27/tests/environment.sh
source "$TEST_FILES/environment.sh" "$@"
other_go=${4:?second Go compiler command}
expected_root="$LIBDIR/golang-${version%.*}"
test "$("$go" env GOROOT)" = "$expected_root"
test "$("$other_go" env GOROOT)" != "$expected_root"
test ! "$(command -v "$other_go")" -ef "$expected_root/bin/go"
CGO_ENABLED=0 "$go" build -o subject-consumer "$TEST_FILES/hello.go"
CGO_ENABLED=0 "$other_go" build -o other-consumer "$TEST_FILES/hello.go"
test "$(./subject-consumer)" = go-ok
test "$(./other-consumer)" = go-ok
