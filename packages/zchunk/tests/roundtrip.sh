#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
for i in {1..200}; do printf 'zchunk content %04d\n' "$i"; done > original
zck -o compressed.zck original
zck_read_header compressed.zck > header
header_text=$(<header)
[[ $header_text == *'Overall checksum type: SHA-256'* ]]
[[ $header_text == *'Chunk checksum type: SHA-512/128'* ]]
# This short input has an empty dictionary entry and one data chunk.
[[ $header_text == *$'\nChunk count: 2\n'* ]]
unzck -c compressed.zck > restored
cmp original restored
printf broken > corrupt.zck
if unzck -c corrupt.zck > invalid.out 2> invalid.log; then exit 1; fi
if zck_read_header corrupt.zck > invalid-header.out 2> invalid-header.log; then exit 1; fi
