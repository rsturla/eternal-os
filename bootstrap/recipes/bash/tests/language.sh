#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
[[ $(bash --noprofile --norc -c 'printf "%s\n" a{1..3}') == $'a1\na2\na3' ]]
a=(one 'two words' three)
[[ ${#a[@]} == 3 && ${a[1]} == 'two words' ]]
declare -A map=([first]=11 [second]=22)
[[ ${map[first]} == 11 ]]
[[ $(printf 'a:b:c' | { IFS=: read -r a b c || :; printf '%s-%s-%s' "$a" "$b" "$c"; }) == a-b-c ]]
[[ $(cat <(printf 'process substitution')) == 'process substitution' ]]
if bash -euo pipefail -c 'false | true'; then exit 1; fi
if bash -eu -c 'false; echo unreachable'; then exit 1; fi
bash -c 'trap "printf trapped > trap.out" EXIT; :'
[[ $(cat trap.out) == trapped ]]
