#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
printf 'alpha 12\nbeta 34\nalpha 56\n' > input
[[ $(grep -n '^alpha' input) == $'1:alpha 12\n3:alpha 56' ]]
[[ $(grep -Eo '[0-9]+' input) == $'12\n34\n56' ]]
[[ $(grep -F 'beta 34' input) == 'beta 34' ]]
[[ $(grep -v alpha input) == 'beta 34' ]]
[[ $(grep -c alpha input) == 2 ]]
[[ $(grep -A1 '^beta' input) == $'beta 34\nalpha 56' ]]
printf 'a.b\naxb\n' > literals
[[ $(grep -Fx a.b literals) == a.b ]]
printf 'left\0right\0' > nul
[[ $(grep -az right nul | tr '\0' '\n') == right ]]
