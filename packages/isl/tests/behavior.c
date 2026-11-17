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
#include <isl/ctx.h>
#include <isl/set.h>
#include <isl/val.h>
int main(void) {
  isl_ctx *c = isl_ctx_alloc();
  CHECK(c);
  isl_set *a = isl_set_read_from_str(c, "{ [i] : 0 <= i <= 9 }");
  CHECK(a);
  isl_set *b = isl_set_read_from_str(c, "{ [i] : 5 <= i <= 14 }");
  CHECK(b);
  isl_set *intersection = isl_set_intersect(a, b);
  CHECK(intersection);
  isl_val *n = isl_set_count_val(intersection);
  CHECK(n && isl_val_get_num_si(n) == 5);
  isl_val_free(n);
  isl_set_free(intersection);
  isl_set *empty = isl_set_read_from_str(c, "{ [i] : i < 0 and i > 0 }");
  CHECK(empty && isl_set_is_empty(empty) == isl_bool_true);
  isl_set_free(empty);
  isl_ctx_free(c);
  return 0;
}
