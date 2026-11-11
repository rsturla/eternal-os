#!/usr/bin/env bash
set -euo pipefail

# Preserve the generated data and identify the actual compiler and reader.
report_failure() {
  status=$?
  trap - EXIT
  if ((status != 0)); then
    cat locale-context.txt >&2 || :
    ls -lnR locale >&2 || :
    if [[ -f locale/en_US.UTF-8/LC_CTYPE ]]; then
      od -An -tx4 -N16 locale/en_US.UTF-8/LC_CTYPE >&2 || :
    fi
  fi
  exit "$status"
}
trap report_failure EXIT
trap 'printf "locale test line %s failed: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

{
  id
  df -P .
  df -iP .
  printf 'localedef: %s\nlocale: %s\n' "$(command -v localedef)" "$(command -v locale)"
  getconf GNU_LIBC_VERSION
  localedef --version
  locale --version
  sha256sum "$(command -v localedef)" "$(command -v locale)" /usr/lib64/libc.so.6
  case "$(uname -m)" in
    x86_64) loader=/usr/lib64/ld-linux-x86-64.so.2 ;;
    aarch64) loader=/usr/lib/ld-linux-aarch64.so.1 ;;
    *) echo 'unsupported locale test architecture' >&2; exit 1 ;;
  esac
  sha256sum "$loader"
  "$loader" --list "$(command -v localedef)"
  "$loader" --list "$(command -v locale)"
  printf 'LANG=%s LC_ALL=%s SOURCE_DATE_EPOCH=%s\n' "${LANG-}" "${LC_ALL-}" "${SOURCE_DATE_EPOCH-}"
  printf 'umask: '
  umask
} > locale-context.txt

mkdir locale
localedef --no-archive -i en_US -f UTF-8 "$PWD/locale/en_US.UTF-8"
actual=$(LOCPATH="$PWD/locale" LC_ALL=en_US.UTF-8 locale charmap)
if [[ $actual != UTF-8 ]]; then
  printf 'expected UTF-8 from the generated locale, got: %s\n' "$actual" >&2
  exit 1
fi
