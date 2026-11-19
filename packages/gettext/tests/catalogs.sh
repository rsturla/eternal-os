#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
[[ $# == 1 ]]
msgfmt --version > msgfmt-version.txt
IFS= read -r version < msgfmt-version.txt
[[ $version == "msgfmt (GNU gettext-tools) $1" ]]
[[ -f /usr/share/gettext/m4/gettext.m4 ]]
[[ -f /usr/share/aclocal/nls.m4 ]]
msgfmt --check -o messages.mo "$TEST_FILES/messages.po"
msgunfmt messages.mo > restored.po
[[ $(cat restored.po) == *'bonjour'* ]]
msgattrib --no-obsolete "$TEST_FILES/messages.po" > clean.po
msgfmt --check -o clean.mo clean.po
printf 'msgid "broken"\nmsgstr\n' > invalid.po
if msgfmt --check -o invalid.mo invalid.po; then exit 1; fi
[[ $(TEXTDOMAIN=missing TEXTDOMAINDIR="$PWD" gettext 'untranslated') == untranslated ]]

# Extract an actual C message and substitute only the requested variable.
printf 'const char *message = gettext("fixture message");\n' > message.c
xgettext --language=C --keyword=gettext --omit-header --no-location -o extracted.po message.c
[[ $(<extracted.po) == *'msgid "fixture message"'* ]]
# Pass literal shell variables to envsubst, which performs the substitution.
# shellcheck disable=SC2016
[[ $(NAME=eternal envsubst <<< 'hello ${NAME}') == 'hello eternal' ]]
# shellcheck disable=SC2016
[[ $(NAME=eternal OTHER=retained envsubst '${NAME}' <<< '${NAME} ${OTHER}') == 'eternal ${OTHER}' ]]
