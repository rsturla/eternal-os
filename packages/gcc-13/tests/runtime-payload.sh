#!/usr/bin/bash
set -euo pipefail
# Inspect the selected RPM's own extraction, not the installed closure.
root=${TEST_PACKAGE_ROOT:?selected runtime payload}
library_dir=${LIBDIR#/}
shopt -s globstar nullglob
runtime_files=0
for path in "$root"/**/*; do
    if [[ -d $path && ! -L $path ]]; then continue; fi
    relative=${path#"$root"/}
    case "$relative" in
        "$library_dir"/libgcc_s.so.*) ((runtime_files += 1)) ;;
        usr/share/licenses/libgcc-13/*) ;;
        *) echo "unexpected file in runtime-only libgcc-13: $relative" >&2; exit 1 ;;
    esac
done
test "$runtime_files" -ge 1
test -f "$root$LIBDIR/libgcc_s.so.1"
# Neither the runtime Requires nor the baseline harness should install tools.
for compiler in /usr/bin/gcc /usr/bin/gcc-* /usr/bin/g++; do
    if [[ -e $compiler ]]; then
        echo "runtime-only libgcc-13 unexpectedly installed $compiler" >&2
        exit 1
    fi
done

for development_file in /usr/bin/ld /usr/bin/as /usr/include/stdio.h; do
    if [[ -e $development_file ]]; then
        echo "runtime-only libgcc unexpectedly installed $development_file" >&2
        exit 1
    fi
done
