#!/usr/bin/env bash
# Check installed target startup objects independently of the policy wrapper.
set -euo pipefail
cc=$1
mkdir branch-protection
cd branch-protection

case "$RPMX_TARGET_ARCH" in
  aarch64)
    features=(BTI PAC)
    compiler_flags=()
    linker_flags=('-Wl,-z,bti-report=error')
    # AArch64 defaults must also protect target objects built by in-tree xgcc.
    "$cc" -dM -E -x c /dev/null > default-macros.txt
    for feature in "${features[@]}"; do
      if ! grep -Eq "^#define __ARM_FEATURE_${feature}_DEFAULT 1$" default-macros.txt; then
        echo "$cc: default $feature protection is disabled" >&2
        exit 1
      fi
    done
    ;;
  x86_64)
    features=(IBT SHSTK)
    compiler_flags=(-fcf-protection=full)
    linker_flags=('-Wl,-z,cet-report=error')
    ;;
  *)
    echo "$cc: unsupported test architecture $RPMX_TARGET_ARCH" >&2
    exit 1
    ;;
esac

# GCC 13 emits GNU notes; newer AArch64 toolchains can use AEABI attributes.
# Inspect every installed start/end variant, not a freshly compiled substitute.
for crt in crtbegin.o crtbeginS.o crtbeginT.o crtend.o crtendS.o; do
  path=$("$cc" -print-file-name="$crt")
  if [[ $path == "$crt" || ! -f $path ]]; then
    echo "$cc: installed startup object $crt is missing ($path)" >&2
    exit 1
  fi
  readelf -nW "$path" > "$crt.notes"
  readelf -AW "$path" > "$crt.attributes"
  for feature in "${features[@]}"; do
    if grep -Eq "Properties:.*$feature" "$crt.notes"; then
      continue
    fi
    if [[ $RPMX_TARGET_ARCH == aarch64 ]] &&
       grep -Eq "Tag_Feature_$feature:[[:space:]]+1([[:space:]]|$)" "$crt.attributes"; then
      continue
    fi
    echo "$cc: installed startup object $path has no $feature protection" >&2
    exit 1
  done
done

# BFD must preserve protection through the actual startup closure.
"$cc" -fuse-ld=bfd "${compiler_flags[@]}" -fPIC -shared "${linker_flags[@]}" \
  "$TEST_FILES/library.c" -o libprobe.so
# Keep the loader token literal in the installed run path.
# shellcheck disable=SC2016
"$cc" -fuse-ld=bfd "${compiler_flags[@]}" "${linker_flags[@]}" "$TEST_FILES/main.c" \
  -L. -lprobe -Wl,-rpath,'$ORIGIN' -o probe
./probe
for binary in libprobe.so probe; do
  readelf -nW "$binary" > "$binary.notes"
  for feature in "${features[@]}"; do
    if ! grep -Eq "Properties:.*$feature" "$binary.notes"; then
      echo "$cc: final $binary has no loader-visible $feature property" >&2
      exit 1
    fi
  done
done
