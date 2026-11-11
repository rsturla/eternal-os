#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
mkdir -p tree/sub
printf one > 'tree/with space'
printf two > tree/sub/two
ln -s sub tree/link
[[ $(find tree -type f | sort) == $'tree/sub/two\ntree/with space' ]]
[[ $(find tree -type l -printf '%l') == sub ]]
find tree -type f -print0 | xargs -0 -n1 printf '<%s>\n' > names
[[ $(sort names) == $'<tree/sub/two>\n<tree/with space>' ]]
[[ $(find tree -type f -exec cat '{}' +) == twoone || $(find tree -type f -exec cat '{}' +) == onetwo ]]
find tree -name two -delete
[[ ! -e tree/sub/two ]]
printf '' | xargs -r sh -c 'exit 99'
