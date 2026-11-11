#include <string.h>
#include <zstd.h>
int main(void) {
  const char input[] = "binary\0payload payload payload";
  char compressed[256], out[256];
  size_t n =
      ZSTD_compress(compressed, sizeof compressed, input, sizeof input, 3);
  if (ZSTD_isError(n))
    return 1;
  size_t m = ZSTD_decompress(out, sizeof out, compressed, n);
  if (ZSTD_isError(m) || m != sizeof input || memcmp(input, out, m))
    return 2;
  if (!ZSTD_isError(ZSTD_decompress(out, 1, compressed, n)))
    return 3;
  compressed[0] ^= 127;
  if (!ZSTD_isError(ZSTD_decompress(out, sizeof out, compressed, n)))
    return 4;
  return 0;
}
