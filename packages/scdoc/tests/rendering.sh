#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
scdoc < "$TEST_FILES/manual.scd" > manual.1
text=$(cat manual.1)
[[ $text == *'.TH "ETERNAL" "1"'* ]]
[[ $text == *'.SH NAME'* && $text == *'eternal'* ]]
[[ $text == *'.SH OPTIONS'* && $text == *'\fB\-\-verbose\fR'* ]]
printf 'this is not a manual header\n' > invalid.scd
if scdoc < invalid.scd > invalid.1; then exit 1; fi
