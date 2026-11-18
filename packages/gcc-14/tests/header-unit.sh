#!/usr/bin/env bash
set -euo pipefail
: "${CXX:?Set CXX to the stream compiler}"
: "${TEST_FILES:?Set TEST_FILES to the fixture directory}"

mkdir header-unit
cd header-unit
cp "$TEST_FILES/math-header.hh" "$TEST_FILES/consumer.cc" .
"$CXX" -std=c++20 -fmodules-ts -x c++-header math-header.hh
# Read the whole unit so imported target types must match the textual <cmath>.
"$CXX" -std=c++20 -fmodules-ts -fno-module-lazy -O2 consumer.cc -o consumer
./consumer 81
if ./consumer 82; then
    echo 'sqrt consumer accepted the wrong expected result' >&2
    exit 1
else
    status=$?
    test "$status" -eq 1
fi
if ./consumer invalid; then
    echo 'sqrt consumer accepted nonnumeric input' >&2
    exit 1
else
    status=$?
    test "$status" -eq 2
fi
