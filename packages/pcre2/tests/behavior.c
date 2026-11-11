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
#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>
int main(void) {
  int error;
  PCRE2_SIZE offset;
  pcre2_code *code =
      pcre2_compile((PCRE2_SPTR) "(?<word>[a-z]+)-([0-9]+)",
                    PCRE2_ZERO_TERMINATED, 0, &error, &offset, NULL);
  CHECK(code);
  pcre2_match_data *match = pcre2_match_data_create_from_pattern(code, NULL);
  CHECK(match);
  CHECK(pcre2_match(code, (PCRE2_SPTR) "hello-42", 8, 0, 0, match, NULL) == 3);
  PCRE2_SIZE *positions = pcre2_get_ovector_pointer(match);
  CHECK(positions[2] == 0 && positions[3] == 5 && positions[4] == 6 &&
        positions[5] == 8);
  CHECK(pcre2_match(code, (PCRE2_SPTR) "no match", 8, 0, 0, match, NULL) ==
        PCRE2_ERROR_NOMATCH);
  CHECK(pcre2_jit_compile(code, PCRE2_JIT_COMPLETE) == 0);
  CHECK(pcre2_jit_match(code, (PCRE2_SPTR) "hello-42", 8, 0, 0, match, NULL) ==
        3);
  pcre2_match_data_free(match);
  pcre2_code_free(code);
  CHECK(!pcre2_compile((PCRE2_SPTR) "[", 1, 0, &error, &offset, NULL));
  return 0;
}
