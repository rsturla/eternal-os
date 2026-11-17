#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
gcc -Wall -Wextra -Werror -fPIC -shared "$TEST_FILES/make-api.c" -o eternal.so
printf 'load ./eternal.so\nall:\n\t@test "$(eternal )" = 42\n' > Makefile
make --no-print-directory
