#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
printf 'one 12\ntwo 34\nthree 56\n' > input
[[ $(sed -n '2p' input) == 'two 34' ]]
[[ $(sed -E 's/([a-z]+) ([0-9]+)/\2:\1/' input) == $'12:one\n34:two\n56:three' ]]
[[ $(sed '1,2d' input) == 'three 56' ]]
[[ $(sed -n '1h;2{G;p;}' input) == $'two 34\none 12' ]]
sed -i.bak 's/two/second/' input
[[ $(sed -n '2p' input) == 'second 34' ]]
[[ $(sed -n '2p' input.bak) == 'two 34' ]]
printf 'a\0b\0' | sed -z 's/b/c/' > nul
[[ $(tr '\0' ':' < nul) == a:c: ]]
