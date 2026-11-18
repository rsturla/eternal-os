#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
gawk -M -v PREC=256 '
function check(condition, message) {
    if (!condition) {
        print "arbitrary precision: " message > "/dev/stderr"
        exit 1
    }
}
BEGIN {
    check(PROCINFO["gmp_version"] != "", "GMP support is missing")
    check(PROCINFO["mpfr_version"] != "", "MPFR support is missing")
    check((2^200 + 1) - 2^200 == 1, "integer addition lost precision")
    check(sprintf("%d", 2^100 + 1) == "1267650600228229401496703205377",
          "large integer formatting is incorrect")
    third = "0.3333333333333333333333333333333333333333333333333333333333333333333333"
    sqrt_two = "1.4142135623730950488016887242096980785696718753769480731766797379907325"
    check(sprintf("%.70f", 1 / 3) == third, "256-bit division is incorrect")
    check(sprintf("%.70f", sqrt(2)) == sqrt_two, "256-bit square root is incorrect")
    ROUNDMODE = "D"
    lower = 1 / 10
    ROUNDMODE = "U"
    upper = 1 / 10
    check(lower < upper, "directed rounding modes are ineffective")
    print "MPFR/GMP precision checks passed"
}'
