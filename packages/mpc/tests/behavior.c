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
#include <mpc.h>
int main(void) {
  mpc_t a, b;
  mpc_init2(a, 128);
  mpc_init2(b, 128);
  mpc_set_si_si(a, 3, 4, MPC_RNDNN);
  mpc_mul(b, a, a, MPC_RNDNN);
  CHECK(mpfr_cmp_si(mpc_realref(b), -7) == 0 &&
        mpfr_cmp_si(mpc_imagref(b), 24) == 0);
  mpc_div(b, b, a, MPC_RNDNN);
  CHECK(mpc_cmp(a, b) == 0);
  mpc_conj(b, a, MPC_RNDNN);
  mpc_mul(b, a, b, MPC_RNDNN);
  CHECK(mpfr_cmp_ui(mpc_realref(b), 25) == 0 && mpfr_zero_p(mpc_imagref(b)));
  CHECK(mpc_set_str(b, "not a number", 10, MPC_RNDNN) == -1);
  mpc_clear(a);
  mpc_clear(b);
  return 0;
}
