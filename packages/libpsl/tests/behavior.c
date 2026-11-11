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
#include <libpsl.h>
int main(void) {
  const psl_ctx_t *p = psl_builtin();
  CHECK(p);
  CHECK(psl_is_public_suffix(p, "com"));
  CHECK(psl_is_public_suffix(p, "co.uk"));
  CHECK(!psl_is_public_suffix(p, "example.com"));
  CHECK(
      !strcmp(psl_registrable_domain(p, "www.example.co.uk"), "example.co.uk"));
  CHECK(psl_registrable_domain(p, "co.uk") == NULL);
  CHECK(!psl_is_cookie_domain_acceptable(p, "www.example.com", "com"));
  CHECK(psl_is_cookie_domain_acceptable(p, "www.example.com", "example.com"));
  return 0;
}
