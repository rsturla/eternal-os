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
#include <cap-ng.h>
#include <linux/capability.h>
int main(void) {
  capng_clear(CAPNG_SELECT_BOTH);
  CHECK(capng_have_capabilities(CAPNG_SELECT_BOTH) == CAPNG_NONE);
  CHECK(capng_update(CAPNG_ADD, CAPNG_EFFECTIVE | CAPNG_PERMITTED, CAP_CHOWN) ==
        0);
  CHECK(capng_have_capability(CAPNG_EFFECTIVE, CAP_CHOWN) == 1);
  CHECK(capng_have_capability(CAPNG_EFFECTIVE, CAP_SYS_ADMIN) == 0);
  CHECK(capng_update(CAPNG_DROP, CAPNG_EFFECTIVE | CAPNG_PERMITTED,
                     CAP_CHOWN) == 0);
  CHECK(capng_have_capabilities(CAPNG_SELECT_BOTH) == CAPNG_NONE);
  CHECK(capng_name_to_capability("chown") == CAP_CHOWN);
  CHECK(capng_name_to_capability("not_a_capability") == -1);
  return 0;
}
