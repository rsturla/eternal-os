#!/usr/bin/env bash
# Inspect this libc's linker inputs directly, independently of GCC startup files.
set -euo pipefail
libdir=$1
arch=$2
case "$arch" in
  x86_64) machine='Advanced Micro Devices X86-64'; features=(IBT SHSTK) ;;
  aarch64) machine=AArch64; features=(BTI PAC) ;;
  *) echo "unsupported CRT target architecture: $arch" >&2; exit 1 ;;
esac
mkdir -p crt-branch-protection/startup crt-branch-protection/nonshared

fail() {
  echo "glibc CRT branch protection: $*" >&2
  exit 1
}

check_object() {
  local object=$1 evidence=$2 feature
  readelf -hW "$object" > "$evidence.header"
  grep -Eq 'Type:[[:space:]]+REL[[:space:]]' "$evidence.header" ||
    fail "$object is not a relocatable ELF object"
  grep -Eq "Machine:[[:space:]]+${machine}[[:space:]]*$" "$evidence.header" ||
    fail "$object does not target $arch"
  readelf -nW "$object" > "$evidence.notes"
  readelf -AW "$object" > "$evidence.attributes"
  for feature in "${features[@]}"; do
    if grep -Eq "Properties:.*[[:space:],]$feature([[:space:],]|$)" "$evidence.notes"; then
      continue
    fi
    # Recent AArch64 assemblers encode the same AND properties as AEABI tags.
    # Require value 1; the presence of a disabled tag must not pass this check.
    if [[ $arch == aarch64 ]] &&
       grep -Eq "Tag_Feature_$feature:[[:space:]]+1([[:space:]]|$)" "$evidence.attributes"; then
      continue
    fi
    fail "$object has no $feature protection; see $evidence.notes and $evidence.attributes"
  done
}

# These inputs cover ordinary, PIE, static PIE, and shared-library startup.
for name in crt1.o Scrt1.o rcrt1.o crti.o crtn.o; do
  [[ -f $libdir/$name ]] || fail "required startup object $libdir/$name is missing"
done
# Include profiling and other installed variants rather than checking one CRT.
for object in "$libdir"/*crt*.o; do
  check_object "$object" "crt-branch-protection/startup/${object##*/}"
done

archive="$libdir/libc_nonshared.a"
[[ -f $archive ]] || fail "required archive $archive is missing"
ar t "$archive" > crt-branch-protection/nonshared-members.txt
[[ -s crt-branch-protection/nonshared-members.txt ]] || fail "$archive has no members"
while IFS= read -r member; do
  case "$member" in
    ''|*/*|.|..|-*) fail "unexpected archive member name: $member" ;;
  esac
  object="crt-branch-protection/nonshared/$member"
  ar p "$archive" "$member" > "$object"
  check_object "$object" "$object"
done < crt-branch-protection/nonshared-members.txt
printf 'glibc CRT and libc_nonshared inputs have %s protection\n' "${features[*]}"
