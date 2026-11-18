#!/usr/bin/env bash
# Verify private link inputs and public runtime selection in an installed cohort.
set -euo pipefail
major=$1
cc=/usr/bin/gcc-$major
cxx=/usr/bin/g++-$major
mkdir -p "runtime-selection/$major"
cd "runtime-selection/$major"

# Versioned compiler files are private; GCC 16 owns the public library cohort.
for library in libgcc_s libstdc++ libatomic libgomp libitm; do
    link_path=$("$cc" -print-file-name="$library.so")
    if [[ ! -f $link_path ]]; then
        echo "GCC $major cannot find $library.so: $link_path" >&2
        exit 1
    fi
    resolved=$(readlink -f "$link_path")
    if (( major < 16 )); then
        case "$resolved" in
            "$LIBDIR"/gcc/*/"$major"/*) ;;
            *) echo "GCC $major links $library outside its private directory: $resolved" >&2; exit 1 ;;
        esac
    fi
    printf '%s -> %s\n' "$library" "$resolved" >> link-inputs.txt
done

"$cxx" -std=c++17 -pthread "$TEST_FILES/containers.cc" -Wl,-Map=cxx.map -o cxx
"$cc" "$TEST_FILES/atomic.c" -latomic -Wl,-Map=atomic.map -o atomic
"$cc" -fopenmp "$TEST_FILES/openmp.c" -Wl,-Map=openmp.map -o openmp
"$cc" -fgnu-tm "$TEST_FILES/transaction.c" -Wl,-Map=transaction.map -o transaction

for entry in 'cxx libstdc++.so.6' 'cxx libgcc_s.so.1' 'atomic libatomic.so.1' 'openmp libgomp.so.1' 'transaction libitm.so.1'; do
    read -r binary soname <<< "$entry"
    readelf -d "$binary" > "$binary.dynamic"
    if grep -E '\((RPATH|RUNPATH)\)' "$binary.dynamic"; then
        echo "GCC $major unexpectedly embedded a runtime search path in $binary" >&2
        exit 1
    fi
    LD_TRACE_LOADED_OBJECTS=1 "./$binary" > "$binary.loader"
    found=0
    while read -r name arrow path rest; do
        if [[ $name == "$soname" && $arrow == '=>' ]]; then
            actual=$(readlink -f "$path")
            expected=$(readlink -f "$LIBDIR/$soname")
            if [[ $actual != "$expected" ]]; then
                echo "GCC $major $binary loaded $soname from $actual, expected $expected" >&2
                exit 1
            fi
            found=1
        fi
    done < "$binary.loader"
    if (( ! found )); then
        echo "GCC $major $binary did not load $soname" >&2
        exit 1
    fi
done

# The compiler's selected library must actually appear in its linker's map.
for entry in 'cxx libstdc++' 'atomic libatomic' 'openmp libgomp' 'transaction libitm'; do
    read -r binary library <<< "$entry"
    link_path=$("$cc" -print-file-name="$library.so")
    grep -F -- "$link_path" "$binary.map"
done
test "$(./cxx)" = cxx-runtime-ok
./atomic
./openmp
./transaction
