#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
[[ -L /usr/bin/sh && -x /usr/bin/sh ]]
[[ $(sh -c 'x=abc; printf "%s" "${x%bc}"') == a ]]
sh -ec 'false && echo unreachable; :'
if sh -ec 'false; echo unreachable'; then exit 1; fi
