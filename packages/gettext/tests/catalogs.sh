#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
msgfmt --check -o messages.mo "$TEST_FILES/messages.po"
msgunfmt messages.mo > restored.po
[[ $(cat restored.po) == *'bonjour'* ]]
msgattrib --no-obsolete "$TEST_FILES/messages.po" > clean.po
msgfmt --check -o clean.mo clean.po
printf 'msgid "broken"\nmsgstr\n' > invalid.po
if msgfmt --check -o invalid.mo invalid.po; then exit 1; fi
[[ $(TEXTDOMAIN=missing TEXTDOMAINDIR="$PWD" gettext 'untranslated') == untranslated ]]
