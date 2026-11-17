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
#include <unicase.h>
#include <unictype.h>
#include <uninorm.h>
#include <unistr.h>
#include <unistdio.h>
int main(void) {
  const uint8_t s[] = "M\303\274nchen";
  CHECK(u8_check(s, sizeof s - 1) == NULL);
  const uint8_t bad[] = {0xff};
  CHECK(u8_check(bad, 1) == bad);
  size_t length = 0;
  uint8_t *upper = u8_toupper(s, sizeof s - 1, NULL, NULL, NULL, &length);
  CHECK(upper && length == 8 && !memcmp(upper, "M\303\234NCHEN", 8));
  free(upper);
  const uint8_t decomposed[] = "e\314\201";
  uint8_t *normalized = u8_normalize(UNINORM_NFC, decomposed, 3, NULL, &length);
  CHECK(normalized && length == 2 && !memcmp(normalized, "\303\251", 2));
  free(normalized);
  CHECK(uc_is_alpha(0x00fc));
  CHECK(!uc_is_alpha('0'));

  /* Missing configure-time iconv modules used to disable these APIs even for
     ASCII. Exercise the installed library in the default C locale. */
  int comparison = 0;
  CHECK(u8_normcoll((const uint8_t *)"alpha", 5,
                    (const uint8_t *)"beta", 4, UNINORM_NFC, &comparison) == 0);
  CHECK(comparison < 0);
  CHECK(u8_normcoll((const uint8_t *)"alpha", 5,
                    (const uint8_t *)"alpha", 5, UNINORM_NFC, &comparison) == 0);
  CHECK(comparison == 0);
  uint8_t *formatted = NULL;
  CHECK(u8_asprintf(&formatted, "value: %s %d", "eternal", 42) == 17);
  CHECK(formatted && !strcmp((const char *)formatted, "value: eternal 42"));
  free(formatted);
  return 0;
}
