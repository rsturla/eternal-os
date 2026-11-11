#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
gcc -Wall -Wextra -Werror -fPIC -shared -I/usr/include/bash -I/usr/include/bash/include -I/usr/include/bash/builtins "$TEST_FILES/builtin.c" -o eternal.so
enable -f "$PWD/eternal.so" eternal
[[ $(eternal) == 'eternal builtin' ]]
enable -d eternal
