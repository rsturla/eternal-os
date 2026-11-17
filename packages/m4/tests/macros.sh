#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
cat > input.m4 <<'EOF'
define(`square', `eval($1 * $1)')dnl
square(7)
ifdef(`square', `present', `missing')
changequote([,])dnl
[quoted $1]
EOF
[[ $(m4 input.m4) == $'49\npresent\nquoted $1' ]]
printf 'included\n' > include.m4
printf "include(\`include.m4')dnl\n" > loader.m4
[[ $(m4 loader.m4) == included ]]
printf "errprint(\`expected failure')m4exit(7)\n" > failure.m4
status=0; m4 failure.m4 > out 2> err || status=$?
[[ $status == 7 && $(cat err) == 'expected failure' ]]
