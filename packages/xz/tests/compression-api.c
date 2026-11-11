#include <lzma.h>
#include <stdint.h>
#include <string.h>
int main(void) {
  const unsigned char input[] = "binary\0payload payload payload";
  unsigned char compressed[256], out[256];
  size_t n = 0, in = 0, m = 0;
  uint64_t limit = UINT64_MAX;
  if (lzma_easy_buffer_encode(6, LZMA_CHECK_CRC64, 0, input, sizeof input,
                              compressed, &n, sizeof compressed) != LZMA_OK)
    return 1;
  if (lzma_stream_buffer_decode(&limit, 0, 0, compressed, &in, n, out, &m,
                                sizeof out) != LZMA_OK ||
      m != sizeof input || memcmp(input, out, m))
    return 2;
  compressed[0] ^= 255;
  in = m = 0;
  if (lzma_stream_buffer_decode(&limit, 0, 0, compressed, &in, n, out, &m,
                                sizeof out) == LZMA_OK)
    return 3;
  return 0;
}
