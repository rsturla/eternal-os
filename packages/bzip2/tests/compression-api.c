#include <bzlib.h>
#include <string.h>
int main(void) {
  char input[] = "binary\0payload payload payload";
  char compressed[256], out[256];
  unsigned int n = sizeof compressed, m = sizeof out;
  if (BZ2_bzBuffToBuffCompress(compressed, &n, input, sizeof input, 9, 0, 30) !=
      BZ_OK)
    return 1;
  if (BZ2_bzBuffToBuffDecompress(out, &m, compressed, n, 0, 0) != BZ_OK ||
      m != sizeof input || memcmp(out, input, m))
    return 2;
  m = 1;
  if (BZ2_bzBuffToBuffDecompress(out, &m, compressed, n, 0, 0) !=
      BZ_OUTBUFF_FULL)
    return 3;
  return 0;
}
