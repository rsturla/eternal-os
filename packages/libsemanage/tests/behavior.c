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
#include <semanage/handle.h>
#include <semanage/port_record.h>
int main(void) {
  semanage_handle_t *h = semanage_handle_create();
  CHECK(h);
  semanage_port_t *p = NULL;
  CHECK(semanage_port_create(h, &p) == 0 && p);
  semanage_port_set_port(p, 443);
  semanage_port_set_proto(p, SEMANAGE_PROTO_TCP);
  CHECK(semanage_port_get_low(p) == 443 && semanage_port_get_high(p) == 443);
  CHECK(semanage_port_get_proto(p) == SEMANAGE_PROTO_TCP);
  semanage_port_t *copy = NULL;
  CHECK(semanage_port_clone(h, p, &copy) == 0 && copy);
  semanage_port_set_range(copy, 8000, 8100);
  CHECK(semanage_port_get_low(copy) == 8000 &&
        semanage_port_get_high(copy) == 8100);
  CHECK(semanage_port_get_low(p) == 443);
  semanage_port_free(copy);
  semanage_port_free(p);
  semanage_handle_destroy(h);
  return 0;
}
