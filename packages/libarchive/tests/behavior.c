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
#include <archive.h>
#include <archive_entry.h>
int main(void) {
  char buffer[8192], payload[32];
  size_t used = 0;
  struct archive *a = archive_write_new();
  CHECK(a);
  CHECK(archive_write_set_format_pax_restricted(a) == ARCHIVE_OK);
  CHECK(archive_write_open_memory(a, buffer, sizeof buffer, &used) ==
        ARCHIVE_OK);
  struct archive_entry *e = archive_entry_new();
  CHECK(e);
  archive_entry_set_pathname(e, "payload.txt");
  archive_entry_set_filetype(e, AE_IFREG);
  archive_entry_set_perm(e, 0644);
  archive_entry_set_size(e, 7);
  CHECK(archive_write_header(a, e) == ARCHIVE_OK);
  CHECK(archive_write_data(a, "payload", 7) == 7);
  archive_entry_free(e);
  CHECK(archive_write_close(a) == ARCHIVE_OK);
  CHECK(archive_write_free(a) == ARCHIVE_OK);
  a = archive_read_new();
  CHECK(a);
  CHECK(archive_read_support_format_all(a) == ARCHIVE_OK);
  CHECK(archive_read_open_memory(a, buffer, used) == ARCHIVE_OK);
  CHECK(archive_read_next_header(a, &e) == ARCHIVE_OK);
  CHECK(!strcmp(archive_entry_pathname(e), "payload.txt"));
  CHECK(archive_entry_size(e) == 7);
  CHECK(archive_read_data(a, payload, sizeof payload) == 7);
  CHECK(!memcmp(payload, "payload", 7));
  CHECK(archive_read_next_header(a, &e) == ARCHIVE_EOF);
  CHECK(archive_read_free(a) == ARCHIVE_OK);
  a = archive_read_new();
  CHECK(a);
  CHECK(archive_read_support_format_all(a) == ARCHIVE_OK);
  CHECK(archive_read_open_memory(a, "not an archive", 14) != ARCHIVE_OK);
  archive_read_free(a);
  return 0;
}
