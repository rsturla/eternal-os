#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
cp "$TEST_FILES/Makefile" .
printf source > input
make -j4 all
[[ $(cat result) == 'source suffix' ]]
[[ $(cat count) == x ]]
make -q all
make all
[[ $(cat count) == x ]]
printf changed > input
touch -d @0 result
touch -d @1 input
make -j4 all
[[ $(cat result) == 'changed suffix' && $(cat count) == xx ]]
if make expected-failure; then exit 1; fi
[[ ! -e broken ]]
make clean
[[ ! -e result ]]
