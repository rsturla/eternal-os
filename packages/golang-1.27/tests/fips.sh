#!/usr/bin/bash
set -euo pipefail
# shellcheck source=packages/golang-1.27/tests/environment.sh
source "$TEST_FILES/environment.sh" "$@"
export CGO_ENABLED=0
root=$("$go" env GOROOT)
test "$("$go" env GOFIPS140)" = certified
test "$("$go" env GOAMD64)" = v2
test "$("$go" env GOARM64)" = v8.0
test "$(env -u GOTOOLCHAIN "$go" env GOTOOLCHAIN)" = local
"$go" build -o fips "$TEST_FILES/fips.go"
snapshot=$(<"$root/lib/fips140/certified.txt")
"$go" version -m fips >fips-build-info.txt
grep -Fx $'\tbuild\tGOFIPS140='"$snapshot" fips-build-info.txt
expected='sha256=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad aead=ok'
# Host-auto must honor the actual procfs policy; the override then exercises
# activation deterministically on ordinary non-FIPS test hosts too.
host_enabled=false
if [[ -r /proc/sys/crypto/fips_enabled && $(</proc/sys/crypto/fips_enabled) = 1 ]]; then
    host_enabled=true
fi
test "$(./fips)" = "enabled=$host_enabled $expected"
test "$(GOLANG_NATIVE_HOSTFIPS_OVERRIDE=1 ./fips)" = "enabled=true $expected"
test "$(GODEBUG=fips140=off ./fips)" = "enabled=false $expected"
test "$(GODEBUG=fips140=on ./fips)" = "enabled=true $expected"
GOFIPS140=off "$go" build -o nonfips "$TEST_FILES/fips.go"
test "$(GOLANG_NATIVE_HOSTFIPS_OVERRIDE=1 GODEBUG=fips140=off ./nonfips)" = "enabled=false $expected"
for option in tag experiment; do
    if [[ $option = tag ]]; then
        "$go" build -tags=strictfipsruntime -o guarded "$TEST_FILES/fips.go"
    else
        GOEXPERIMENT=strictfipsruntime "$go" build -o guarded "$TEST_FILES/fips.go"
    fi
    test "$(GOLANG_NATIVE_HOSTFIPS_OVERRIDE=1 ./guarded)" = "enabled=true $expected"
    if [[ $host_enabled = false ]]; then
        test "$(GODEBUG=fips140=off ./guarded)" = "enabled=false $expected"
    fi
    status=0
    GOLANG_NATIVE_HOSTFIPS_OVERRIDE=1 GODEBUG=fips140=off ./guarded >"guard-$option.stdout" 2>"guard-$option.stderr" || status=$?
    test "$status" = 1
    test ! -s "guard-$option.stdout"
    test "$(<"guard-$option.stderr")" = 'Host FIPS mode is enabled, but the required GODEBUG=fips140 module is disabled'
done
