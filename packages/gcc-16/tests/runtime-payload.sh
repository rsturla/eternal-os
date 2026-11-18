#!/usr/bin/env bash
set -euo pipefail
package=$1
library=$2
root=${TEST_PACKAGE_ROOT:?selected runtime payload}
library_dir=${LIBDIR#/}
shopt -s globstar nullglob
runtime_files=0
for path in "$root"/**/*; do
    if [[ -d $path && ! -L $path ]]; then continue; fi
    relative=${path#"$root"/}
    case "$relative" in
        "$library_dir"/"$library".so.*) ((runtime_files += 1)) ;;
        usr/share/licenses/"$package"/*) ;;
        usr/share/rpmx/buildinfo/"$package".json) ;;
        usr/share/sbom/"$package-"*.spdx.json) ;;
        *) echo "unexpected file in runtime-only $package: $relative" >&2; exit 1 ;;
    esac
done
test "$runtime_files" -ge 1
# The runtime's own dependency closure must not install compiler tools or headers.
for development_file in /usr/bin/gcc /usr/bin/gcc-* /usr/bin/g++ /usr/bin/ld /usr/bin/as /usr/include/stdio.h; do
    if [[ -e $development_file ]]; then
        echo "runtime-only $package unexpectedly installed $development_file" >&2
        exit 1
    fi
done
