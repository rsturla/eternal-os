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
#include <popt.h>
int main(void) {
  int number = 0, verbose = 0;
  struct poptOption options[] = {
      {"number", 'n', POPT_ARG_INT, &number, 0, NULL, NULL},
      {"verbose", 'v', POPT_ARG_NONE, &verbose, 0, NULL, NULL},
      POPT_TABLEEND};
  const char *args[] = {"test", "--number", "42", "-v", "payload"};
  poptContext c = poptGetContext(NULL, 5, args, options, 0);
  CHECK(c);
  CHECK(poptGetNextOpt(c) == -1);
  CHECK(number == 42 && verbose == 1);
  CHECK(!strcmp(poptGetArg(c), "payload"));
  CHECK(poptGetArg(c) == NULL);
  poptFreeContext(c);
  const char *bad[] = {"test", "--unknown"};
  c = poptGetContext(NULL, 2, bad, options, 0);
  CHECK(c);
  CHECK(poptGetNextOpt(c) == POPT_ERROR_BADOPT);
  poptFreeContext(c);
  return 0;
}
