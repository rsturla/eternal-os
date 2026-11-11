#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <zck.h>

#define CHECK(expression)                                                      \
  do {                                                                         \
    if (!(expression)) {                                                       \
      fprintf(stderr, "%s:%d: failed: %s\n", __FILE__, __LINE__, #expression);   \
      return 1;                                                                \
    }                                                                          \
  } while (0)

int main(void) {
  const char input[] = "zchunk\0binary\377payload";
  char decoded[sizeof input];
  FILE *file = tmpfile();
  CHECK(file != NULL);
  int fd = fileno(file);
  CHECK(fd >= 0);

  zckCtx *writer = zck_create();
  CHECK(writer != NULL);
  CHECK(zck_init_write(writer, fd));
  CHECK(zck_set_ioption(writer, ZCK_COMP_TYPE, ZCK_COMP_ZSTD));
  CHECK(zck_write(writer, input, 5) == 5);
  CHECK(zck_write(writer, input + 5, sizeof input - 5) == sizeof input - 5);
  /* Closing finalizes the header and its checksums before any reader starts. */
  CHECK(zck_close(writer));
  CHECK(zck_get_chunk_count(writer) > 0);
  zck_free(&writer);
  CHECK(writer == NULL);

  CHECK(lseek(fd, 0, SEEK_SET) == 0);
  zckCtx *reader = zck_create();
  CHECK(reader != NULL);
  CHECK(zck_init_read(reader, fd));
  size_t offset = 0;
  while (offset < sizeof decoded) {
    ssize_t count = zck_read(reader, decoded + offset, 1);
    CHECK(count == 1);
    offset += (size_t)count;
  }
  CHECK(memcmp(decoded, input, sizeof input) == 0);
  CHECK(zck_read(reader, decoded, sizeof decoded) == 0);
  CHECK(zck_close(reader));
  zck_free(&reader);
  CHECK(reader == NULL);

  /* A damaged file signature must fail at read initialization, with an error. */
  unsigned char signature;
  CHECK(pread(fd, &signature, 1, 0) == 1);
  signature ^= 0xff;
  CHECK(pwrite(fd, &signature, 1, 0) == 1);
  CHECK(lseek(fd, 0, SEEK_SET) == 0);
  reader = zck_create();
  CHECK(reader != NULL);
  CHECK(!zck_init_read(reader, fd));
  CHECK(zck_is_error(reader) != 0);
  CHECK(zck_get_error(reader)[0] != '\0');
  zck_free(&reader);
  CHECK(fclose(file) == 0);
  return 0;
}
