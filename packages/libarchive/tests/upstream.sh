#!/usr/bin/env bash
set -euo pipefail

# Upstream ownership tests require root and nobody to exist. Supply private
# account data without changing the sandbox's read-only /etc or host accounts.
rm -rf upstream-results
mkdir upstream-results
export NSS_WRAPPER_PASSWD="$PWD/upstream-results/passwd"
export NSS_WRAPPER_GROUP="$PWD/upstream-results/group"
printf 'root:x:0:0:root:/root:/bin/sh\nnobody:x:65534:65534:nobody:/nonexistent:/bin/false\n' > "$NSS_WRAPPER_PASSWD"
printf 'root:x:0:\nnobody:x:65534:\n' > "$NSS_WRAPPER_GROUP"
if [[ $(id -u) != 0 && $(id -u) != 65534 ]]; then
  printf 'rpmx-test:x:%s:%s:test:/tmp:/bin/sh\n' "$(id -u)" "$(id -g)" >> "$NSS_WRAPPER_PASSWD"
fi
if [[ $(id -g) != 0 && $(id -g) != 65534 ]]; then
  printf 'rpmx-test:x:%s:\n' "$(id -g)" >> "$NSS_WRAPPER_GROUP"
fi
export LD_PRELOAD="$LIBDIR/libnss_wrapper.so"
test -r "$LD_PRELOAD"
test "$(id -u root)" = 0
test "$(id -g root)" = 0

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
