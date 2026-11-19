#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
mkdir -p tree/sub
: > "$PWD/tree/sub/needle"
printf '%s\n' "$PWD/tree" "$PWD/tree/sub" "$PWD/tree/sub/needle" | /usr/libexec/findutils/frcode > locatedb
[[ $(locate -d "$PWD/locatedb" needle) == "$PWD/tree/sub/needle" ]]
if locate -d "$PWD/locatedb" absent; then exit 1; fi
