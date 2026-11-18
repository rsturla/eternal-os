#!/usr/bin/env bash
set -euo pipefail
major=$1
root=${TEST_PACKAGE_ROOT:?selected compiler payload}
shopt -s nullglob
commands=("$root"/usr/bin/*)
if (( ${#commands[@]} == 0 )); then
    echo "GCC $major compiler payload contains no commands" >&2
    exit 1
fi
# Only the separate default selector may own unversioned commands.
for path in "${commands[@]}"; do
    case ${path##*/} in
        *-"$major") ;;
        *) echo "unversioned command in GCC $major payload: ${path#"$root"}" >&2; exit 1 ;;
    esac
done
for command in gcc g++ cpp; do
    test -x "$root/usr/bin/$command-$major"
done
