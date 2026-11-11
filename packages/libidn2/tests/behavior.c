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
#include <idn2.h>
int main(void) {
  uint8_t *ascii = NULL;
  char *unicode = NULL;
  CHECK(idn2_lookup_u8((const uint8_t *)"m\303\274nchen.de", &ascii,
                       IDN2_NFC_INPUT | IDN2_NONTRANSITIONAL) == IDN2_OK);
  CHECK(!strcmp((char *)ascii, "xn--mnchen-3ya.de"));
  CHECK(idn2_to_unicode_8z8z((char *)ascii, &unicode, 0) == IDN2_OK);
  CHECK(!strcmp(unicode, "m\303\274nchen.de"));
  idn2_free(ascii);
  idn2_free(unicode);
  ascii = NULL;
  CHECK(idn2_lookup_u8((const uint8_t *)"\377.example", &ascii, 0) != IDN2_OK);
  idn2_free(ascii);
  return 0;
}
