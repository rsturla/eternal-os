#!/usr/bin/env bash
set -euo pipefail
: "${TEST_FILES:?Set TEST_FILES to the fixture directory}"

# Compare the exact upstream loop at O0 and O3 with an independent O0 oracle.
/usr/bin/gcc-16 -O0 -Dis_sorted=original_is_sorted -c "$TEST_FILES/sorted-early-exit.c" -o original.o
/usr/bin/gcc-16 -O3 -Dis_sorted=optimized_is_sorted -c "$TEST_FILES/sorted-early-exit.c" -o optimized.o
/usr/bin/gcc-16 -O0 "$TEST_FILES/sorted-early-exit-oracle.c" original.o optimized.o -o sorted-early-exit
./sorted-early-exit

/usr/bin/gcc-16 -O0 -DWRONG_IMPLEMENTATION "$TEST_FILES/sorted-early-exit-oracle.c" original.o -o wrong-implementation
if ./wrong-implementation 2>wrong-implementation.stderr; then
    echo 'early-exit oracle accepted a deliberately wrong implementation' >&2
    exit 1
else
    status=$?
    test "$status" -eq 1
fi
