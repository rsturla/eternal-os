#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
printf payload > target
setfattr -n user.eternal -v 'value with spaces' target
[[ $(getfattr --only-values -n user.eternal target) == 'value with spaces' ]]
setfattr -n user.eternal -v 0x0001ff target
[[ $(getfattr -e hex -n user.eternal target) == *'user.eternal=0x0001ff'* ]]
getfattr -d -e hex target > saved.xattr
setfattr -x user.eternal target
if getfattr -n user.eternal target; then exit 1; fi
setfattr --restore=saved.xattr
[[ $(getfattr -e hex -n user.eternal target) == *'user.eternal=0x0001ff'* ]]
