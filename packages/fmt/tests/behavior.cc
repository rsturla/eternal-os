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
#include <fmt/format.h>
#include <fmt/ranges.h>
#include <vector>
int main() {
  CHECK(fmt::format("{} {:04x} {:.2f}", "answer", 42, 3.14159) ==
        "answer 002a 3.14");
  CHECK(fmt::format("{1}/{0}", "left", "right") == "right/left");
  CHECK(fmt::format("{}", std::vector<int>{1, 2, 3}) == "[1, 2, 3]");
  bool failed = false;
  try {
    (void)fmt::format(fmt::runtime("{:invalid}"), 42);
  } catch (const fmt::format_error &) {
    failed = true;
  }
  CHECK(failed);
  return 0;
}
