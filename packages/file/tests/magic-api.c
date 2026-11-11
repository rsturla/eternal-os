#include <magic.h>
#include <string.h>
int main(void) {
  magic_t m = magic_open(MAGIC_MIME_TYPE);
  if (!m)
    return 1;
  if (magic_load(m, 0)) {
    magic_close(m);
    return 2;
  }
  const char *kind = magic_buffer(m, "plain text\n", 11);
  int result = !kind || strcmp(kind, "text/plain");
  magic_close(m);
  return result;
}
