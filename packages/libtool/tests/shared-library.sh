#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
cp "$TEST_FILES/library.c" "$TEST_FILES/main.c" .
libtool --mode=compile gcc -c library.c -o library.lo
libtool --mode=link gcc -rpath "$PWD/dest" -version-info 1:0:0 library.lo -o libfixture.la
libtool --mode=link gcc main.c libfixture.la -o consumer
[[ $(./consumer) == 42 ]]
mkdir dest
libtool --mode=install install -c libfixture.la "$PWD/dest/libfixture.la"
[[ -f dest/libfixture.so.1 ]]
gcc main.c -L"$PWD/dest" -lfixture -Wl,-rpath,"$PWD/dest" -o installed-consumer
[[ $(./installed-consumer) == 42 ]]
libtool --mode=clean rm -f libfixture.la library.lo consumer
