#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
gcc -Wall -Wextra -Werror "$TEST_FILES/gettext-api.c"  -lgettextpo -o probe
./probe "$TEST_FILES/messages.po"
if ./probe "$TEST_FILES/invalid.po" >invalid.out 2>&1; then
  printf 'libgettextpo accepted an invalid catalog\n' >&2
  exit 1
fi
[[ $(<invalid.out) == *'gettext diagnostic:'* ]]
