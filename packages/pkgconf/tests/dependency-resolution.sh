#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
export PKG_CONFIG_LIBDIR="$TEST_FILES/pkgconfig"
export PKG_CONFIG_PATH=
[[ $(pkgconf --modversion fixture) == 1.2.3 ]]
pkgconf --exists 'fixture >= 1.2'
if pkgconf --exists 'fixture >= 2'; then exit 1; fi
[[ $(pkgconf --cflags fixture) == *'-I/opt/fixture/include'* ]]
[[ $(pkgconf --libs fixture) == *'-lfixture'* && $(pkgconf --libs fixture) != *'-lprivate'* ]]
[[ $(pkgconf --static --libs fixture) == *'-lprivate'* ]]
[[ $(pkg-config --variable=prefix fixture) == /opt/fixture ]]
export PKG_CONFIG_SYSROOT_DIR=/sysroot
[[ $(pkgconf --cflags fixture) == *'-I/sysroot/opt/fixture/include'* ]]
if pkgconf --exists missing-eternal-module; then exit 1; fi
