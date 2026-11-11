#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define CHECK(expr)                                                            \
  do {                                                                         \
    if (!(expr)) {                                                             \
      fprintf(stderr, "%s:%d: %s failed\n", __FILE__, __LINE__, #expr);        \
      return 1;                                                                \
    }                                                                          \
  } while (0)
#include <mpfr.h>
int main(void) {
  mpfr_t a, b;
  mpfr_inits2(256, a, b, (mpfr_ptr)0);
  mpfr_set_ui(a, 2, MPFR_RNDN);
  mpfr_sqrt(b, a, MPFR_RNDN);
  mpfr_mul(b, b, b, MPFR_RNDN);
  mpfr_sub(b, b, a, MPFR_RNDN);
  mpfr_abs(b, b, MPFR_RNDN);
  CHECK(mpfr_cmp_d(b, 1e-70) < 0);
  mpfr_set_ui(a, 1, MPFR_RNDN);
  mpfr_div_ui(a, a, 3, MPFR_RNDD);
  mpfr_set_ui(b, 1, MPFR_RNDN);
  mpfr_div_ui(b, b, 3, MPFR_RNDU);
  CHECK(mpfr_less_p(a, b));
  mpfr_set_ui(a, 0, MPFR_RNDN);
  mpfr_log(b, a, MPFR_RNDN);
  CHECK(mpfr_inf_p(b) && mpfr_signbit(b));
  mpfr_set_si(a, -1, MPFR_RNDN);
  mpfr_sqrt(b, a, MPFR_RNDN);
  CHECK(mpfr_nan_p(b));
  mpfr_clears(a, b, (mpfr_ptr)0);
  mpfr_free_cache();
  return 0;
}
