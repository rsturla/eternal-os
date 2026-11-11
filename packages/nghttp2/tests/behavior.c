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
#include <nghttp2/nghttp2.h>
int main(void) {
  nghttp2_hd_deflater *encoder = NULL;
  nghttp2_hd_inflater *decoder = NULL;
  CHECK(nghttp2_hd_deflate_new(&encoder, 4096) == 0);
  CHECK(nghttp2_hd_inflate_new(&decoder) == 0);
  nghttp2_nv headers[] = {
      {(uint8_t *)":method", (uint8_t *)"GET", 7, 3, NGHTTP2_NV_FLAG_NONE},
      {(uint8_t *)":path", (uint8_t *)"/test", 5, 5, NGHTTP2_NV_FLAG_NONE}};
  uint8_t buffer[1024];
  ssize_t size =
      nghttp2_hd_deflate_hd(encoder, buffer, sizeof buffer, headers, 2);
  CHECK(size > 0);
  size_t offset = 0, count = 0, calls = 0;
  int flags = 0;
  do {
    CHECK(++calls <= (size_t)size + 3);
    nghttp2_nv nv;
    ssize_t n = nghttp2_hd_inflate_hd2(decoder, &nv, &flags, buffer + offset,
                                       size - offset, 1);
    CHECK(n >= 0);
    offset += n;
    if (flags & NGHTTP2_HD_INFLATE_EMIT) {
      CHECK(count < 2);
      CHECK(nv.namelen == headers[count].namelen &&
            nv.valuelen == headers[count].valuelen);
      CHECK(!memcmp(nv.name, headers[count].name, nv.namelen));
      CHECK(!memcmp(nv.value, headers[count].value, nv.valuelen));
      ++count;
    }
  } while (!(flags & NGHTTP2_HD_INFLATE_FINAL));
  CHECK(count == 2 && offset == (size_t)size);
  CHECK(nghttp2_hd_inflate_end_headers(decoder) == 0);
  /* RFC 7541 section 6.1 / appendix A: static index 2 means :method GET.
     Decode fixed wire bytes so a matching encoder defect cannot pass. */
  const uint8_t indexed[] = {0x82};
  nghttp2_nv nv;
  CHECK(nghttp2_hd_inflate_hd2(decoder, &nv, &flags, indexed, sizeof indexed,
                               1) == 1);
  CHECK(flags & NGHTTP2_HD_INFLATE_EMIT);
  CHECK(nv.namelen == 7 && !memcmp(nv.name, ":method", 7));
  CHECK(nv.valuelen == 3 && !memcmp(nv.value, "GET", 3));
  if (!(flags & NGHTTP2_HD_INFLATE_FINAL)) {
    CHECK(nghttp2_hd_inflate_hd2(decoder, &nv, &flags, indexed + sizeof indexed,
                                 0, 1) == 0);
    CHECK(!(flags & NGHTTP2_HD_INFLATE_EMIT));
  }
  CHECK(flags & NGHTTP2_HD_INFLATE_FINAL);
  CHECK(nghttp2_hd_inflate_end_headers(decoder) == 0);
  /* Index zero is forbidden by section 6.1. */
  const uint8_t invalid[] = {0x80};
  CHECK(nghttp2_hd_inflate_hd2(decoder, &nv, &flags, invalid, sizeof invalid,
                               1) == NGHTTP2_ERR_HEADER_COMP);
  nghttp2_hd_deflate_del(encoder);
  nghttp2_hd_inflate_del(decoder);
  return 0;
}
