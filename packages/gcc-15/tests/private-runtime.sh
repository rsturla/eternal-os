#!/usr/bin/env bash
set -euo pipefail
major=$1
library=$2
shopt -s nullglob
matches=()
for path in "$LIBDIR"/gcc/*/"$major"/"$library".so.*; do
    version=${path##*/}
    version=${version#"$library.so."}
    # libstdc++ also ships a GDB Python helper beside its ELF library.
    if [[ $library == libstdc++ && $version =~ ^[0-9]+(\.[0-9]+)*-gdb\.py$ ]]; then
        continue
    fi
    if [[ ! $version =~ ^[0-9]+(\.[0-9]+)*$ ]]; then
        echo "unexpected private GCC $major runtime filename: $path" >&2
        exit 1
    fi
    matches+=("$path")
done
if (( ${#matches[@]} == 0 )); then
    echo "missing private GCC $major $library runtime" >&2
    exit 1
fi
# Private libraries are link inputs; installed consumers must use the public runtime.
public=("$LIBDIR/$library".so.*)
test "${#public[@]}" -ge 1
test -f "${public[0]}"
loaders=(/lib*/ld-linux-*.so.*)
test "${#loaders[@]}" -ge 1
for path in "${matches[@]}"; do
    "${loaders[0]}" --list "$path"
done
# No global SONAME files may escape into this selected private RPM's payload.
root=${TEST_PACKAGE_ROOT:?selected private runtime payload}
for path in "$root"/usr/lib*/"$library".so.*; do
    echo "private GCC $major runtime owns public path: $path" >&2
    exit 1
done
