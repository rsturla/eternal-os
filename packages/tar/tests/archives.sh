#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
mkdir -p tree/sub out
printf 'archive payload\000binary\377' > tree/sub/file
ln tree/sub/file tree/hard
ln -s sub/file tree/link
chmod 640 tree/sub/file
tar --format=pax -cf archive.tar tree
tar -tf archive.tar > listing
tar -xf archive.tar -C out
cmp tree/sub/file out/tree/sub/file
[[ $(readlink out/tree/link) == sub/file ]]
[[ $(stat -c %i out/tree/hard) == $(stat -c %i out/tree/sub/file) ]]
[[ $(stat -c %a out/tree/sub/file) == 640 ]]
tar -df archive.tar
printf changed >> tree/sub/file
if tar -df archive.tar > changed.log; then exit 1; fi
printf broken > broken.tar
if tar -tf broken.tar > broken.log 2>&1; then exit 1; fi
