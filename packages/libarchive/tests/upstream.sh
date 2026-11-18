#!/usr/bin/env bash
set -euo pipefail

# Use the real account database supplied by the test-only setup package.
# Account lookup interposition changes ACL identity restoration semantics.
test "$(id -u root)" = 0
test "$(id -g root)" = 0
test "$(id -u nobody)" = 65534
test "$(id -g nobody)" = 65534
rm -rf upstream-results
mkdir upstream-results

# The upstream harness writes its detailed failing-case logs under TMPDIR.
# Keep those beside the aggregate report so rpmx can retain both on failure.
export TMPDIR="$PWD/upstream-results"

# Cover filename conversion and normalization with private locale data. The
# SHIFT_JIS charmap intentionally triggers the non-ASCII-compatibility warning;
# suppress that warning only, keeping localedef failures fatal.
for tool in locale localedef lz4 lzop; do
  command -v "$tool" >/dev/null || {
    echo "libarchive upstream tests require $tool" >&2
    exit 1
  }
done
export LOCPATH="$TMPDIR/locales"
mkdir "$LOCPATH"
while read -r source charmap name; do
  localedef --no-archive --no-warnings=ascii -i "$source" -f "$charmap" "$LOCPATH/$name"
  actual=$(LC_ALL="$name" locale charmap)
  [[ $actual == "$charmap" ]] || {
    echo "libarchive locale $name: expected charmap $charmap, got $actual" >&2
    echo "locale data: $LOCPATH/$name" >&2
    exit 1
  }
done <<'LOCALES'
en_US UTF-8 en_US.UTF-8
en_US ISO-8859-1 en_US.ISO8859-1
ja_JP EUC-JP ja_JP.eucJP
ja_JP SHIFT_JIS ja_JP.SJIS
ru_RU KOI8-R ru_RU.KOI8-R
ru_RU CP1251 ru_RU.CP1251
ru_RU IBM866 ru_RU.CP866
LOCALES

# Include skip reasons in the retained program logs, not just "skipped" labels.
export _VERBOSITY_LEVEL=1
make -j"$JOBS" check
