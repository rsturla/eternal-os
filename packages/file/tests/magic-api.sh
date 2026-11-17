#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
gcc -Wall -Wextra -Werror "$TEST_FILES/magic-api.c" -lmagic -o probe
./probe
