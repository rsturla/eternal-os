#!/usr/bin/env bash
set -euo pipefail

if ! grep -q '^#define HAVE_ICONV 1$' config.h; then
  echo 'libunistring was configured without iconv; check buildroot conversion modules' >&2
  exit 1
fi

# Supply real locale data privately for the Linux conversion and thread tests.
# Keep the generated data with the reports; do not alter the root's locales.
mkdir -p upstream-results/locales
export LOCPATH="$PWD/upstream-results/locales"
while read -r source charmap name; do
  localedef --no-archive -i "$source" -f "$charmap" "$LOCPATH/$name"
  actual=$(LC_ALL="$name" locale charmap)
  [[ $actual == "$charmap" ]] || {
    echo "libunistring locale $name: expected charmap $charmap, got $actual" >&2
    exit 1
  }
done <<'LOCALES'
en_US UTF-8 en_US.UTF-8
fr_FR ISO-8859-1 fr_FR.ISO-8859-1
fr_FR UTF-8 fr_FR.UTF-8
de_DE UTF-8 de_DE.UTF-8
tr_TR UTF-8 tr_TR.UTF-8
ja_JP EUC-JP ja_JP.eucJP
zh_CN GB18030 zh_CN.GB18030
ar_SA ISO-8859-6 ar_SA.ISO-8859-6
LOCALES

# Configure records test-only locale selectors as "none" in a minimal root.
# Automake's test-command wrapper selects the verified private locales while
# retaining all of upstream's TESTS_ENVIRONMENT and every test case.
test_locales=(
  LOCALE_EN_UTF8=en_US.UTF-8
  LOCALE_FR=fr_FR.ISO-8859-1
  LOCALE_FR_UTF8=fr_FR.UTF-8
  LOCALE_TR_UTF8=tr_TR.UTF-8
  LOCALE_JA=ja_JP.eucJP
  LOCALE_ZH_CN=zh_CN.GB18030
  LOCALE_AR=ar_SA.ISO-8859-6
)
make check LOG_COMPILER="env ${test_locales[*]}"
