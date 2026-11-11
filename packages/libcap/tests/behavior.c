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
#include <sys/capability.h>
int main(void) {
  cap_t c = cap_from_text("cap_chown,cap_net_bind_service=ep");
  CHECK(c);
  cap_flag_value_t value;
  CHECK(cap_get_flag(c, CAP_CHOWN, CAP_EFFECTIVE, &value) == 0 &&
        value == CAP_SET);
  CHECK(cap_get_flag(c, CAP_SYS_ADMIN, CAP_EFFECTIVE, &value) == 0 &&
        value == CAP_CLEAR);
  cap_t copy = cap_dup(c);
  CHECK(copy && cap_compare(c, copy) == 0);
  CHECK(cap_clear_flag(copy, CAP_EFFECTIVE) == 0);
  CHECK(cap_compare(c, copy) != 0);
  char *text = cap_to_text(c, NULL);
  CHECK(text && strstr(text, "cap_chown"));
  cap_free(text);
  cap_free(copy);
  cap_free(c);
  CHECK(cap_from_text("no_such_capability=ep") == NULL);
  return 0;
}
