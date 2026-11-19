#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "failed at %s:%s: %s\n" "$0" "$LINENO" "$BASH_COMMAND" >&2' ERR
export LC_ALL=C
for directory in /usr/lib/bash /usr/lib64/bash; do
  if [[ -f $directory/basename && -f $directory/dirname ]]; then
    enable -f "$directory/basename" basename
    enable -f "$directory/dirname" dirname
    [[ $(type -t basename) == builtin && $(type -t dirname) == builtin ]]
    [[ $(basename /usr/bin/bash) == bash ]]
    [[ $(dirname /usr/bin/bash) == /usr/bin ]]
    enable -d basename
    enable -d dirname
    exit 0
  fi
done
printf 'basename and dirname loadable builtins are missing\n' >&2
exit 1
