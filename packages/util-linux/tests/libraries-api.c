#include <blkid/blkid.h>
#include <libfdisk/libfdisk.h>
#include <libmount/libmount.h>
#include <libsmartcols/libsmartcols.h>
#include <string.h>
#include <uuid/uuid.h>
int main(void) {
  uuid_t a, b;
  char text[37];
  uuid_generate(a);
  uuid_unparse(a, text);
  if (uuid_parse(text, b) || uuid_compare(a, b))
    return 1;
  struct libmnt_table *t = mnt_new_table();
  struct libmnt_fs *fs = mnt_new_fs();
  if (!t || !fs)
    return 2;
  if (mnt_fs_set_source(fs, "LABEL=fixture") ||
      mnt_fs_set_target(fs, "/data") || mnt_table_add_fs(t, fs) ||
      mnt_table_get_nents(t) != 1)
    return 3;
  mnt_unref_fs(fs);
  mnt_unref_table(t);
  blkid_probe p = blkid_new_probe();
  if (!p)
    return 4;
  blkid_free_probe(p);
  struct fdisk_context *f = fdisk_new_context();
  if (!f)
    return 5;
  fdisk_unref_context(f);
  struct libscols_table *s = scols_new_table();
  if (!s || !scols_table_new_column(s, "NAME", 0, 0))
    return 6;
  struct libscols_line *line = scols_table_new_line(s, 0);
  if (!line || scols_line_set_data(line, 0, "fixture"))
    return 7;
  scols_unref_table(s);
  return 0;
}
