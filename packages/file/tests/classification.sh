#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
printf 'plain text\n' > plain
printf '\211PNG\r\n\032\n\000\000\000\015IHDR\000\000\000\001\000\000\000\001\010\002\000\000\000' > image
[[ $(file -b --mime-type plain) == text/plain ]]
[[ $(file -b --mime-type image) == image/png ]]
[[ $(file -b --mime-type /usr/bin/file) == application/x-executable || $(file -b --mime-type /usr/bin/file) == application/x-pie-executable ]]
printf '0 string ETERNAL Eternal fixture format\n' > custom.magic
printf 'ETERNALdata' > custom
[[ $(file -b -m custom.magic custom) == 'Eternal fixture format' ]]
file -C -m custom.magic
[[ $(file -b -m custom.magic.mgc custom) == 'Eternal fixture format' ]]
