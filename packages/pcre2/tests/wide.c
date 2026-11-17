#include <pcre2.h>
#include <stdio.h>

#define CHECK(expr)                                                            \
  do {                                                                         \
    if (!(expr)) {                                                             \
      fprintf(stderr, "%s:%d: %s failed\n", __FILE__, __LINE__, #expr);        \
      return 1;                                                                \
    }                                                                          \
  } while (0)

int main(void) {
  PCRE2_UCHAR pattern[] = {'a', '+', 0};
  PCRE2_UCHAR subject[] = {'a', 'a', 'a', 0};
  PCRE2_UCHAR missing[] = {'b', 0};
  PCRE2_UCHAR invalid[] = {'[', 0};
  int error = 0;
  PCRE2_SIZE offset = 0;
  pcre2_code *code =
      pcre2_compile(pattern, PCRE2_ZERO_TERMINATED, 0, &error, &offset, NULL);
  CHECK(code);
  pcre2_match_data *match = pcre2_match_data_create_from_pattern(code, NULL);
  CHECK(match);
  CHECK(pcre2_match(code, subject, 3, 0, 0, match, NULL) == 1);
  PCRE2_SIZE *positions = pcre2_get_ovector_pointer(match);
  CHECK(positions[0] == 0 && positions[1] == 3);
  CHECK(pcre2_match(code, missing, 1, 0, 0, match, NULL) ==
        PCRE2_ERROR_NOMATCH);
  CHECK(pcre2_jit_compile(code, PCRE2_JIT_COMPLETE) == 0);
  CHECK(pcre2_jit_match(code, subject, 3, 0, 0, match, NULL) == 1);
  pcre2_match_data_free(match);
  pcre2_code_free(code);
  CHECK(
      !pcre2_compile(invalid, PCRE2_ZERO_TERMINATED, 0, &error, &offset, NULL));
  return 0;
}
