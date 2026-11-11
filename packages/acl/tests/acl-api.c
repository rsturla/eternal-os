#include <acl/libacl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/acl.h>
int main(void) {
  acl_t a = acl_from_text("u::rw-,g::r--,o::---");
  if (!a || acl_valid(a))
    return 1;
  acl_t b = acl_dup(a);
  if (!b || acl_cmp(a, b))
    return 2;
  ssize_t n = 0;
  char *text = acl_to_text(b, &n);
  if (!text || n <= 0 || !strstr(text, "user::rw-"))
    return 3;
  acl_free(text);
  acl_free(b);
  acl_free(a);
  a = acl_from_text("invalid");
  if (a) {
    acl_free(a);
    return 4;
  }
  return 0;
}
