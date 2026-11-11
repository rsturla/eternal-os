#!/usr/bin/bash
set -euo pipefail
# shellcheck source=packages/golang-1.27/tests/environment.sh
source "$TEST_FILES/environment.sh" "$@"
stream=${version%.*}
test /usr/bin/go -ef "/usr/bin/go-$stream"
test /usr/bin/gofmt -ef "/usr/bin/gofmt-$stream"
CGO_ENABLED=0 "$go" build -o selector-consumer "$TEST_FILES/hello.go"
test "$(./selector-consumer)" = go-ok
"$gofmt" "$TEST_FILES/format.input" >formatted.go
cmp formatted.go "$TEST_FILES/format.expected"
