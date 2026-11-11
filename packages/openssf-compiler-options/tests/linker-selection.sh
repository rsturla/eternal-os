#!/usr/bin/env bash
set -euo pipefail
trap 'printf "line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

# Inspect the real driver's commands without requiring an alternate linker.
gcc -### -x c /dev/null -o probe 2> default-driver.txt
if [[ $RPMX_TARGET_ARCH == aarch64 ]]; then
  grep -F -- '-fuse-ld=bfd' default-driver.txt
fi

gcc -### -fuse-ld=gold -x c /dev/null -o probe 2> explicit-driver.txt
grep -F -- '-fuse-ld=gold' explicit-driver.txt
if grep -F -- '-fuse-ld=bfd' explicit-driver.txt; then
  echo 'architecture policy overrode the explicit linker selection' >&2
  exit 1
fi
