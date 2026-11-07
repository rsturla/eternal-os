#!/usr/bin/env bash
# List the target architectures declared by a profile as a JSON array.
#
# Profiles in this repository use the inline form `archs: [x86_64, aarch64]`.
# That keeps the parser dependency-free on GitHub runners; the profiles are
# reviewed, so a block-style list is a deliberate error rather than something
# to guess at.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
profile=${1:-"$root/profiles/eternal.profile.yaml"}

if [[ ! -f $profile ]]; then
  echo "profile not found: $profile" >&2
  exit 1
fi

arches=$(sed -n 's/^archs:[[:space:]]*\[\(.*\)\].*/\1/p' "$profile" | head -n 1)
if [[ -z $arches ]]; then
  echo "cannot parse an inline 'archs: [..]' list from $profile" >&2
  exit 1
fi

printf '%s\n' "$arches" |
  tr ',' '\n' |
  sed 's/[[:space:]"]//g' |
  sed "s/'//g" |
  sed '/^$/d' |
  sort -u |
  jq -R -s -c 'split("\n") | map(select(length > 0))'
