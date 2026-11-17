#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
printf 'alice:10\nbob:20\nalice:5\n' > input
[[ $(awk -F: '{sum[$1]+=$2} END {print sum["alice"],sum["bob"]}' input) == '15 20' ]]
[[ $(gawk 'BEGIN {print sprintf("%04d", 42); print and(15,6)}') == $'0042\n6' ]]
[[ $(gawk 'BEGIN {split("a,b,c", a, ","); print length(a), a[2]}') == '3 b' ]]
[[ $(gawk 'BEGIN {print gensub(/([a-z]+)([0-9]+)/,"\\2-\\1","g","abc12")}') == 12-abc ]]
[[ $(gawk 'BEGIN {a["z"]=3;a["a"]=1;n=asorti(a,b);for(i=1;i<=n;i++)print b[i]}') == $'a\nz' ]]
if gawk 'BEGIN {' > invalid.out 2> invalid.err; then
  printf 'gawk accepted an unterminated program\n' >&2
  exit 1
fi
[[ -s invalid.err ]]
