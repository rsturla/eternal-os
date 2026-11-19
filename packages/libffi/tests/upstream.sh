#!/usr/bin/env bash
set -euo pipefail

status=0
make check || status=$?

# Configure places the DejaGNU results below its target-triplet directory.
# Retain regular reports even when make fails; never collect scratch FIFOs.
if ! mkdir -p upstream-results || ! find . \
  -path ./upstream-results -prune -o -type f \
  \( -name libffi.log -o -name libffi.sum \) \
  -exec cp -t upstream-results -- {} +; then
  echo 'could not retain libffi DejaGNU reports' >&2
  if ((status != 0)); then exit "$status"; fi
  exit 1
fi
if [[ ! -s upstream-results/libffi.log || ! -s upstream-results/libffi.sum ]]; then
  echo 'libffi upstream tests did not produce DejaGNU reports' >&2
  if ((status != 0)); then exit "$status"; fi
  exit 1
fi
exit "$status"
