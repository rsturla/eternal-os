#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
bzip2 -d -c "$TEST_FILES/vectors/known.bz2" > known.output
cmp "$TEST_FILES/vectors/payload.bin" known.output
for i in {1..200}; do printf 'repeated payload %04d\000binary\377\n' "$i"; done > original
bzip2 -c original > compressed
bzip2 -t compressed
bzip2 -d -c compressed > restored
cmp original restored
: > empty
bzip2 -c empty > empty.compressed
bzip2 -d -c empty.compressed > empty.restored
[[ ! -s empty.restored ]]
printf 'not a compressed stream' > corrupt
if bzip2 -d -c corrupt > invalid.out 2> invalid.log; then exit 1; fi
head -c 12 "$TEST_FILES/vectors/known.bz2" > truncated
if bzip2 -d -c truncated > partial.out 2> truncated.log; then exit 1; fi
