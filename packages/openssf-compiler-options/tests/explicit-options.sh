#!/usr/bin/env bash
# Policy supplies hardened defaults; explicit compiler choices must still work.
set -Eeuo pipefail
trap 'printf "explicit options: line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

cc=$1
shift
source_file="$TEST_FILES/explicit-options.c"
mkdir -p explicit-options

check_fortify() {
  local expected=$1
  shift
  "$cc" "$@" -dM -E -x c /dev/null > optimization.macros
  "$cc" "$@" -Werror=cpp "$source_file" -o optimization
  output=$(./optimization)
  test "$output" = explicit-options-ok
  if [[ $expected == enabled ]]; then
    grep -Fx '#define __OPTIMIZE__ 1' optimization.macros
    grep -Fx '#define _FORTIFY_SOURCE 3' optimization.macros
  else
    if grep -E '^#define (__OPTIMIZE__|_FORTIFY_SOURCE) ' optimization.macros; then
      echo 'optimization-off compile unexpectedly forces Fortify' >&2
      exit 1
    fi
  fi
}

for policy in "$@"; do
  export GCC_SPEC_FILE=$policy
  mkdir -p "explicit-options/$policy"
  pushd "explicit-options/$policy" >/dev/null
  "$cc" -dM -E -x c /dev/null > default.macros
  grep -E '^#define __PIE__ [12]$' default.macros
  grep -Fx '#define __SSP_STRONG__ 3' default.macros
  grep -Fx '#define _FORTIFY_SOURCE 3' default.macros
  "$cc" "$source_file" -o default
  readelf -h default > default.elf
  grep -E 'Type:[[:space:]]+DYN' default.elf
  output=$(./default)
  test "$output" = explicit-options-ok

  for option in -fno-pie -fno-PIE -fno-pic -fno-PIC; do
    # Artifact services can treat names case-insensitively.
    case $option in
      -fno-pie) label=lowercase-pie ;;
      -fno-PIE) label=uppercase-pie ;;
      -fno-pic) label=lowercase-pic ;;
      -fno-PIC) label=uppercase-pic ;;
    esac
    "$cc" "$option" -dM -E -x c /dev/null > "$label.macros"
    if grep -E '^#define __(PIE|PIC)__ ' "$label.macros"; then
      echo "$policy overrides explicit $option" >&2
      exit 1
    fi
    "$cc" "$option" -no-pie "$source_file" -o non-pie
    readelf -h non-pie > "$label.elf"
    grep -E 'Type:[[:space:]]+EXEC' "$label.elf"
    output=$(./non-pie)
    test "$output" = explicit-options-ok
  done

  # The final optimization flag decides whether Fortify can operate.
  check_fortify disabled -O0
  check_fortify enabled -O2
  check_fortify enabled -O0 -O2
  check_fortify disabled -O2 -O0
  popd >/dev/null
done
