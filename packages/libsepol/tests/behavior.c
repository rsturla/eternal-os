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
#include <sepol/context_record.h>
#include <sepol/handle.h>
int main(void) {
  sepol_handle_t *h = sepol_handle_create();
  CHECK(h);
  sepol_context_t *c = NULL;
  CHECK(sepol_context_from_string(h, "system_u:object_r:tmp_t:s0", &c) == 0 &&
        c);
  CHECK(!strcmp(sepol_context_get_user(c), "system_u"));
  CHECK(!strcmp(sepol_context_get_type(c), "tmp_t"));
  CHECK(sepol_context_set_type(h, c, "var_t") == 0);
  char *s = NULL;
  CHECK(sepol_context_to_string(h, c, &s) == 0 && s);
  CHECK(!strcmp(s, "system_u:object_r:var_t:s0"));
  free(s);
  sepol_context_free(c);
  sepol_handle_destroy(h);
  return 0;
}
