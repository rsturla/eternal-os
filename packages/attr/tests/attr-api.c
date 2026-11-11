#include <attr/libattr.h>
#include <stdio.h>
#include <string.h>
#include <sys/xattr.h>

int main(void) {
  const char value[] = "binary\0attribute\377";
  const char *paths[] = {"source-file", "destination-file"};
  for (unsigned int i = 0; i < 2; ++i) {
    FILE *file = fopen(paths[i], "w");
    if (!file)
      return 1;
    if (fclose(file))
      return 2;
  }
  if (setxattr(paths[0], "user.eternal", value, sizeof value, 0))
    return 3;
  if (attr_copy_file(paths[0], paths[1], NULL, NULL))
    return 4;
  char copied[64];
  ssize_t length = getxattr(paths[1], "user.eternal", copied, sizeof copied);
  if (length != sizeof value || memcmp(copied, value, sizeof value))
    return 5;
  if (attr_copy_file("missing-source", paths[1], NULL, NULL) == 0)
    return 6;
  return 0;
}
