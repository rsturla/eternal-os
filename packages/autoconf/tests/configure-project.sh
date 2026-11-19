#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
cp "$TEST_FILES/configure.ac" .
autoheader
autoconf
[[ -s configure ]]
./configure --enable-feature=yes
[[ $(cat config.h) == *'#define HAVE_STDIO_H 1'* && $(cat config.h) == *'#define FEATURE_ENABLED 1'* ]]
[[ -s config.log && -s config.status ]]
./config.status
if ./configure --enable-feature=invalid; then exit 1; fi
