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
#include <readline/history.h>
#include <readline/readline.h>
int main(void) {
  using_history();
  clear_history();
  add_history("first");
  add_history("second");
  CHECK(history_length == 2);
  CHECK(!strcmp(history_get(history_base)->line, "first"));
  char *expanded = NULL;
  CHECK(history_expand("!!", &expanded) == 1);
  CHECK(!strcmp(expanded, "second"));
  free(expanded);
  CHECK(write_history("history.txt") == 0);
  clear_history();
  CHECK(read_history("history.txt") == 0 && history_length == 2);
  rl_initialize();
  rl_replace_line("hello", 0);
  CHECK(!strcmp(rl_line_buffer, "hello"));
  clear_history();
  return 0;
}
