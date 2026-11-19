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
#include <selinux/context.h>
#include <selinux/label.h>
#include <selinux/selinux.h>
int main(void) {
  context_t c = context_new("system_u:object_r:tmp_t:s0");
  CHECK(c);
  CHECK(!strcmp(context_user_get(c), "system_u"));
  CHECK(!strcmp(context_type_get(c), "tmp_t"));
  CHECK(context_type_set(c, "var_t") == 0);
  CHECK(!strcmp(context_str(c), "system_u:object_r:var_t:s0"));
  context_free(c);
  FILE *f = fopen("file_contexts", "w");
  CHECK(f);
  CHECK(fputs("/test(/.*)? system_u:object_r:tmp_t:s0\n", f) >= 0);
  CHECK(fclose(f) == 0);
  struct selinux_opt options[] = {{SELABEL_OPT_PATH, "file_contexts"}};
  struct selabel_handle *h = selabel_open(SELABEL_CTX_FILE, options, 1);
  CHECK(h);
  char *label = NULL;
  CHECK(selabel_lookup_raw(h, &label, "/test/file", 0) == 0);
  CHECK(!strcmp(label, "system_u:object_r:tmp_t:s0"));
  freecon(label);
  CHECK(selabel_lookup_raw(h, &label, "/missing", 0) == -1);
  selabel_close(h);
  return 0;
}
