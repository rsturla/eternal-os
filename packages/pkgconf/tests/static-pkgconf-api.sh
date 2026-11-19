#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
read -r -a flags <<< "$(pkg-config --cflags libpkgconf)"
gcc -Wall -Wextra -Werror "$TEST_FILES/pkgconf-api.c" "${flags[@]}" -Wl,-Bstatic -lpkgconf -Wl,-Bdynamic -o probe
./probe
