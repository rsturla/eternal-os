#!/usr/bin/env bash
set -euo pipefail
major=$1
root=${TEST_PACKAGE_ROOT:?selected compiler payload}
shopt -s nullglob
for path in "$root"/usr/lib*/lib*.so* "$root"/usr/include/c++; do
    if [[ -e $path || -L $path ]]; then
        echo "GCC $major compiler payload collides with public runtime/header path: ${path#"$root"}" >&2
        exit 1
    fi
done
for library in libgcc_s libgomp libitm; do
    matches=("$root$LIBDIR"/gcc/*/"$major"/"$library".so.*)
    if (( ${#matches[@]} == 0 )); then
        echo "GCC $major compiler payload lacks private $library runtime" >&2
        exit 1
    fi
done
