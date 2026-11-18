#!/usr/bin/env bash
set -euo pipefail
: "${TEST_FILES:?Set TEST_FILES to the fixture directory}"

arch_flags=()
if [[ ${RPMX_TARGET_ARCH:?Set RPMX_TARGET_ARCH} == x86_64 ]]; then
    arch_flags=(-march=x86-64 -dp)
fi

# Keep the original optimization levels and an independently compiled oracle.
/usr/bin/gcc-16 -Os "${arch_flags[@]}" -c "$TEST_FILES/byte-swap.c" -o byte-swap.o
/usr/bin/gcc-16 -O2 -c "$TEST_FILES/byte-swap-call.c" -o byte-swap-call.o
/usr/bin/gcc-16 -O0 "$TEST_FILES/byte-swap-oracle.c" byte-swap.o byte-swap-call.o -o byte-swap
./byte-swap

/usr/bin/gcc-16 -O0 -DWRONG_ORACLE "$TEST_FILES/byte-swap-oracle.c" byte-swap.o byte-swap-call.o -o wrong-oracle
if ./wrong-oracle 2>wrong-oracle.stderr; then
    echo 'byte-swap control accepted a deliberately wrong oracle' >&2
    exit 1
else
    status=$?
    test "$status" -eq 1
fi
