#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
flex -o scanner.c "$TEST_FILES/scanner.l"
gcc -Wall -Wextra -Werror scanner.c -o scanner
[[ $(printf 'alpha 12\nbeta 34\n' | ./scanner) == $'word:alpha\nnumber:12\nword:beta\nnumber:34' ]]
if printf '?' | ./scanner; then exit 1; fi
lex -o lex.c "$TEST_FILES/scanner.l"
gcc lex.c -o lex-scanner
[[ $(printf '99' | ./lex-scanner) == number:99 ]]
