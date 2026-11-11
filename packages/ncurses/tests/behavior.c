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
#include <curses.h>
#include <term.h>
int main(void) {
  int error = 0;
  CHECK(setupterm("xterm", 1, &error) == OK && error == 1);
  CHECK(tigetnum("colors") >= 8);
  CHECK(tigetstr("cup") != NULL && tigetstr("cup") != (char *)-1);
  CHECK(tigetnum("nonexistent-capability") == -2);
  CHECK(del_curterm(cur_term) == OK);
  FILE *input = tmpfile(), *output = tmpfile();
  CHECK(input && output);
  SCREEN *screen = newterm("xterm", output, input);
  CHECK(screen);
  WINDOW *window = newwin(4, 20, 0, 0);
  CHECK(window);
  CHECK(mvwaddstr(window, 1, 2, "hello") == OK);
  CHECK((mvwinch(window, 1, 2) & A_CHARTEXT) == 'h');
  CHECK(werase(window) == OK);
  CHECK((mvwinch(window, 1, 2) & A_CHARTEXT) == ' ');
  CHECK(delwin(window) == OK);
  CHECK(endwin() == OK || !isatty(fileno(output)));
  delscreen(screen);
  fclose(input);
  fclose(output);
  return 0;
}
