#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
uuid=$(uuidgen --random)
[[ $uuid =~ ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]]
[[ $(printf 'abc' | hexdump -v -e '1/1 "%02x"') == 616263 ]]
printf 'LABEL=fixture /data ext4 defaults 0 2\n' > fstab
[[ $(findmnt --fstab --tab-file fstab --noheadings --output TARGET) == /data ]]
flock lockfile bash -c 'if flock -n lockfile true; then exit 1; fi'
flock -n lockfile true
printf '[eternal]\nkey = value\n' > config
[[ $(getopt -o ab: -- -a -b value) == " -a -b 'value' --" ]]
truncate -s 16M disk.img
printf 'label: dos\n,8M,L\n' | sfdisk disk.img
sfdisk --dump disk.img > partitions
[[ $(cat partitions) == *'type=83'* ]]
