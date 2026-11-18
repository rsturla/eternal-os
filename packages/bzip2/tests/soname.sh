#!/usr/bin/env bash
set -euo pipefail
libdir=$1
real="$libdir/libbz2.so.1.0.8"
readelf --dynamic "$real" > dynamic.txt
grep -E '\(SONAME\)[[:space:]]+Library soname: \[libbz2\.so\.1\.0\]$' dynamic.txt
for name in libbz2.so.1.0 libbz2.so.1; do
    if [[ ! "$libdir/$name" -ef "$real" ]]; then
        echo "$name must resolve to the upstream libbz2 implementation" >&2
        exit 1
    fi
done
