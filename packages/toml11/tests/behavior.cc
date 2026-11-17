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
#include <sstream>
#include <toml.hpp>
int main() {
  std::istringstream input("title = 'eternal'\nanswer = 42\nvalues = [1, 2, "
                           "3]\n[server]\nenabled = true\n");
  auto v = toml::parse(input, "fixture.toml");
  CHECK(toml::find<std::string>(v, "title") == "eternal");
  CHECK(toml::find<int>(v, "answer") == 42);
  CHECK(toml::find<std::vector<int>>(v, "values") ==
        std::vector<int>({1, 2, 3}));
  CHECK(toml::find<bool>(v, "server", "enabled"));
  bool failed = false;
  try {
    std::istringstream bad("answer = [\n");
    (void)toml::parse(bad, "bad.toml");
  } catch (const toml::syntax_error &) {
    failed = true;
  }
  CHECK(failed);
  return 0;
}
