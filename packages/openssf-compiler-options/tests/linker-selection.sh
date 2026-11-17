#!/usr/bin/env bash
set -euo pipefail
trap 'printf "line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

# Inspect the real driver's commands without requiring an alternate linker.
gcc -### -x c /dev/null -o probe 2> default-driver.txt
# Configure metadata can mention linker flags that are not active. Inspect
# GCC's effective options, and fail if the driver omits that trace entirely.
grep '^COLLECT_GCC_OPTIONS=' default-driver.txt > default-options.txt
if [[ $RPMX_TARGET_ARCH == aarch64 ]]; then
  grep -F -- "'-fuse-ld=bfd'" default-options.txt
fi

gcc -### -fuse-ld=gold -x c /dev/null -o probe 2> explicit-driver.txt
grep '^COLLECT_GCC_OPTIONS=' explicit-driver.txt > explicit-options.txt
grep -F -- "'-fuse-ld=gold'" explicit-options.txt
if grep -F -- "'-fuse-ld=bfd'" explicit-options.txt; then
  echo 'architecture policy overrode the explicit linker selection' >&2
  exit 1
fi
