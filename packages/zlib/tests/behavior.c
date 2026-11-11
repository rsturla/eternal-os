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
#include <zlib.h>
int main(void) {
  const unsigned char input[] = "eternal\0binary\377payload";
  unsigned char compressed[256], output[256];
  uLongf size = sizeof compressed, length = sizeof output;
  /* Fixed interoperability vector: Python 3 zlib.compress(b"hello", 6).
     Keep this independent of the candidate encoder. */
  const unsigned char known[] = {0x78, 0x9c, 0xcb, 0x48, 0xcd, 0xc9, 0xc9,
                                 0x07, 0x00, 0x06, 0x2c, 0x02, 0x15};
  CHECK(uncompress(output, &length, known, sizeof known) == Z_OK);
  CHECK(length == 5 && !memcmp(output, "hello", 5));
  length = sizeof output;
  CHECK(compress2(compressed, &size, input, sizeof input, Z_BEST_COMPRESSION) ==
        Z_OK);
  CHECK(uncompress(output, &length, compressed, size) == Z_OK);
  CHECK(length == sizeof input && memcmp(output, input, length) == 0);
  length = 1;
  CHECK(uncompress(output, &length, compressed, size) == Z_BUF_ERROR);
  compressed[0] ^= 255;
  length = sizeof output;
  CHECK(uncompress(output, &length, compressed, size) == Z_DATA_ERROR);
  CHECK(crc32(0, (const Bytef *)"123456789", 9) == 0xcbf43926UL);
  gzFile f = gzopen("roundtrip.gz", "wb");
  CHECK(f);
  CHECK(gzwrite(f, input, sizeof input) == sizeof input);
  CHECK(gzclose(f) == Z_OK);
  f = gzopen("roundtrip.gz", "rb");
  CHECK(f);
  CHECK(gzread(f, output, sizeof output) == sizeof input);
  CHECK(memcmp(input, output, sizeof input) == 0);
  CHECK(gzclose(f) == Z_OK);
  return 0;
}
