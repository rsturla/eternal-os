#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
cp "$TEST_FILES/configure.ac" "$TEST_FILES/Makefile.am" "$TEST_FILES/hello.c" .
aclocal
autoconf
automake --add-missing --copy
./configure --prefix="$PWD/dest"
make -j2
make check
make install
[[ $(dest/bin/hello) == 'Eternal automake fixture' ]]
make distcheck
make uninstall
[[ ! -e dest/bin/hello ]]
