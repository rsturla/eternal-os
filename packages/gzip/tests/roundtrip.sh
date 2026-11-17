#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
gzip -d -c "$TEST_FILES/vectors/known.gz" > known.output
cmp "$TEST_FILES/vectors/payload.bin" known.output
for i in {1..200}; do printf 'repeated payload %04d\000binary\377\n' "$i"; done > original
gzip -c original > compressed
gzip -t compressed
gzip -d -c compressed > restored
cmp original restored
: > empty
gzip -c empty > empty.compressed
gzip -d -c empty.compressed > empty.restored
[[ ! -s empty.restored ]]
printf 'not a compressed stream' > corrupt
if gzip -d -c corrupt > invalid.out 2> invalid.log; then exit 1; fi
head -c 12 "$TEST_FILES/vectors/known.gz" > truncated
if gzip -d -c truncated > partial.out 2> truncated.log; then exit 1; fi
