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
    # Compare the shell's exports with what a freshly executed child receives.
    # This helps distinguish missing locale data from loader environment filtering.
    for diagnostic_key in LOCPATH LD_PRELOAD LC_ALL LC_CTYPE LC_MESSAGES LANG; do
      printf 'shell %s=%s\n' "$diagnostic_key" "${!diagnostic_key-<unset>}" >&2
      if diagnostic_value=$(printenv "$diagnostic_key"); then
        printf 'child %s=%s\n' "$diagnostic_key" "$diagnostic_value" >&2
      else
        printf 'child %s=<unset>\n' "$diagnostic_key" >&2
      fi
    done
    id >&2 || :
    stat -c '%A %a %u:%g %n' "$LOCPATH" "$LOCPATH/$name" "$LOCPATH/$name/LC_CTYPE" >&2 || :
    # Both supported architectures use 64-bit auxiliary-vector entries.
    while read -r diagnostic_type diagnostic_value; do
      if [[ $diagnostic_type == 23 ]]; then
        printf 'child AT_SECURE=%s\n' "$diagnostic_value" >&2
      fi
    done < <(od -An -v -w16 -t u8 /proc/self/auxv)
    cat /proc/self/attr/current >&2 || :
    diagnostic_locale=$(command -v locale)
    printf 'locale executable: %s\n' "$diagnostic_locale" >&2
    stat -L -c 'locale executable mode=%a uid=%u gid=%g path=%n' "$diagnostic_locale" >&2 || :
    if command -v getcap >/dev/null 2>&1; then
      getcap "$diagnostic_locale" >&2 || :
    fi
    locale --version >&2 || :
    # Retain the actual file lookups and mappings; tracing is diagnostic only.
    diagnostic_prefix="$PWD/upstream-results/locale-load"
    if ! LC_ALL="$name" strace -f -s 256 -o "$diagnostic_prefix.trace" \
      -e trace=%file,read,pread64,mmap,munmap,close locale charmap \
      >"$diagnostic_prefix.stdout" 2>"$diagnostic_prefix.stderr"; then
      echo 'locale tracing failed; retaining the original locale failure' >&2
    fi
    cat "$diagnostic_prefix.stdout" "$diagnostic_prefix.stderr" >&2 || :
    tail -n 40 "$diagnostic_prefix.trace" >&2 || :
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
