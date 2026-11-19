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
#include <gmp.h>
int main(void) {
  mpz_t a, b, c, q, r;
  mpz_inits(a, b, c, q, r, NULL);
  CHECK(mpz_set_str(a, "123456789012345678901234567890", 10) == 0);
  mpz_set_ui(b, 97);
  mpz_mul(c, a, b);
  mpz_tdiv_qr(q, r, c, b);
  CHECK(mpz_cmp(q, a) == 0 && mpz_cmp_ui(r, 0) == 0);
  mpz_gcd(c, a, b);
  CHECK(mpz_cmp_ui(c, 1) == 0);
  CHECK(mpz_invert(c, b, a) != 0);
  mpz_mul(c, c, b);
  mpz_mod(c, c, a);
  CHECK(mpz_cmp_ui(c, 1) == 0);
  CHECK(mpz_set_str(c, "invalid", 10) == -1);
  mpz_clears(a, b, c, q, r, NULL);
  mpq_t x, y;
  mpq_inits(x, y, NULL);
  mpq_set_ui(x, 1, 3);
  mpq_set_ui(y, 2, 3);
  mpq_add(x, x, y);
  CHECK(mpq_cmp_ui(x, 1, 1) == 0);
  mpq_clears(x, y, NULL);
  return 0;
}
