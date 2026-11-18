#!/usr/bin/env bash
# Test direct compiler commands without the package-build policy wrapper.
set -euo pipefail
: "${TEST_FILES:?Set TEST_FILES to the fixture directory}"
: "${RPMX_TARGET_ARCH:?Set RPMX_TARGET_ARCH}"
mkdir default-hardening
cd default-hardening

for language in c c++; do
    compiler=$1
    shift
    "$compiler" -x "$language" -dM -E - </dev/null > "$language.macros"
    grep -Eq '^#define __PIE__ [12]$' "$language.macros"
    grep -Eq '^#define __SSP_(STRONG|ALL)__ [1-9][0-9]*$' "$language.macros"
    if [[ $RPMX_TARGET_ARCH == aarch64 ]]; then
        grep -Eq '^#define __ARM_FEATURE_BTI_DEFAULT 1$' "$language.macros"
        grep -Eq '^#define __ARM_FEATURE_PAC_DEFAULT [1-9][0-9]*$' "$language.macros"
    fi

    "$compiler" -x "$language" "$TEST_FILES/default-hardening.c" -o "$language-default"
    "./$language-default"
    readelf -hW "$language-default" > "$language-default.header"
    readelf --dyn-syms -W "$language-default" > "$language-default.symbols"
    grep -Eq 'Type:[[:space:]]+DYN' "$language-default.header"
    grep -Eq 'UND[[:space:]]+__stack_chk_fail(@|[[:space:]]|$)' "$language-default.symbols"

    # The fixture must detect both protections disappearing under explicit overrides.
    "$compiler" -fno-pie -no-pie -fno-stack-protector -x "$language" \
        "$TEST_FILES/default-hardening.c" -o "$language-control"
    "./$language-control"
    readelf -hW "$language-control" > "$language-control.header"
    readelf --dyn-syms -W "$language-control" > "$language-control.symbols"
    grep -Eq 'Type:[[:space:]]+EXEC' "$language-control.header"
    if grep -Eq '__stack_chk_fail' "$language-control.symbols"; then
        echo "$compiler: negative control still has a stack canary" >&2
        exit 1
    fi
done
