#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
makeinfo --no-split -o sample.info "$TEST_FILES/sample.texi"
[[ $(cat sample.info) == *'Eternal documentation fixture.'* ]]
texi2any --html --no-split -o sample.html "$TEST_FILES/sample.texi"
[[ $(cat sample.html) == *'<html'* && $(cat sample.html) == *'Eternal documentation fixture.'* ]]
texi2any --plaintext -o sample.txt "$TEST_FILES/sample.texi"
[[ $(cat sample.txt) == *'Eternal documentation fixture.'* ]]
install-info sample.info dir
[[ $(cat dir) == *'Eternal fixture'* ]]
info --file "$PWD/sample.info" --node Top --output readback
[[ $(cat readback) == *'Eternal documentation fixture.'* ]]
install-info --delete sample.info dir
[[ $(cat dir) != *'Eternal fixture'* ]]
