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
#include <rhash.h>
int main(void) {
  unsigned char digest[64];
  char hex[130];
  rhash_library_init();
  CHECK(rhash_msg(RHASH_SHA256, "abc", 3, digest) == 0);
  CHECK(rhash_print_bytes(hex, digest, 32, RHPR_HEX) == 64);
  CHECK(!strcmp(
      hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
  rhash context = rhash_init(RHASH_SHA256 | RHASH_CRC32);
  CHECK(context);
  CHECK(rhash_update(context, "a", 1) == 0);
  CHECK(rhash_update(context, "bc", 2) == 0);
  CHECK(rhash_final(context, NULL) == 0);
  CHECK(rhash_print(hex, context, RHASH_SHA256, RHPR_HEX) == 64);
  CHECK(!strcmp(
      hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
  CHECK(rhash_print(hex, context, RHASH_CRC32, RHPR_HEX) == 8);
  CHECK(!strcmp(hex, "352441c2"));
  rhash_free(context);
  return 0;
}
