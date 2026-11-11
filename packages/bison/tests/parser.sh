#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
bison --defines=parser.h -o parser.c "$TEST_FILES/parser.y"
gcc -Wall -Wextra -Werror parser.c -o parser
printf '2+3+4\n' | ./parser > result
[[ $(cat result) == 9 ]]
if printf '2+?\n' | ./parser; then exit 1; fi
yacc -o yacc.c "$TEST_FILES/parser.y"
gcc yacc.c -o yacc-parser
[[ $(printf '7+8\n' | ./yacc-parser) == 15 ]]
