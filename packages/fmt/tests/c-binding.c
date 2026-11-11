#include <fmt/fmt-c.h>
#include <stdio.h>
#include <string.h>

#define CHECK(expr)                                                            \
  do {                                                                         \
    if (!(expr)) {                                                             \
      fprintf(stderr, "%s:%d: %s failed\n", __FILE__, __LINE__, #expr);        \
      return 1;                                                                \
    }                                                                          \
  } while (0)

int main(void) {
  char buffer[64] = {0};
  CHECK(fmt_format(buffer, sizeof buffer, "value {}", 42) == 8);
  CHECK(!strcmp(buffer, "value 42"));
  CHECK(fmt_format(buffer, sizeof buffer, "{:04x}", 42) == 4);
  CHECK(!memcmp(buffer, "002a", 4));
  CHECK(fmt_format(buffer, sizeof buffer, "{:invalid}", 42) == fmt_error);
  return 0;
}
