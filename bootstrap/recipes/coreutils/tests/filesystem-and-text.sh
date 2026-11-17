#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
mkdir -p tree/sub copy
printf 'beta\nalpha\nalpha\n' > tree/sub/input
cp -a tree/. copy/
cmp_output=$(cat copy/sub/input)
[[ $cmp_output == $'beta\nalpha\nalpha' ]]
ln tree/sub/input hard
ln -s tree/sub/input soft
[[ $(stat -c %i hard) == $(stat -c %i tree/sub/input) ]]
[[ $(readlink soft) == tree/sub/input ]]
chmod 640 hard
[[ $(stat -c %a hard) == 640 ]]
mv copy/sub/input copy/sub/moved
[[ $(sort tree/sub/input | uniq -c) == $'      2 alpha\n      1 beta' ]]
[[ $(cut -c1 tree/sub/input | paste -sd, -) == b,a,a ]]
[[ $(wc -l < tree/sub/input) == 3 ]]
[[ $(printf 'ABC' | tr A-Z a-z) == abc ]]
printf 'abc' > bytes
[[ $(sha256sum bytes) == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad  bytes' ]]
sha256sum bytes > hashes
sha256sum -c hashes
printf 'corrupt' >> bytes
if sha256sum -c hashes; then exit 1; fi
printf 'binary\000data\377' > binary
base64 binary > encoded
base64 -d encoded > decoded
[[ $(sha256sum < binary) == $(sha256sum < decoded) ]]
[[ $(seq -s, 2 2 6) == 2,4,6 ]]
[[ $(expr 7 + 5) == 12 ]]
[[ $(date -u -d @0 +%FT%TZ) == 1970-01-01T00:00:00Z ]]
[[ $(realpath soft) == "$PWD/tree/sub/input" ]]
install -Dm600 tree/sub/input installed/file
[[ $(stat -c %a installed/file) == 600 ]]
