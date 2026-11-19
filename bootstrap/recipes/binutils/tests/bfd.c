#define PACKAGE "eternal-bfd-probe"
#include <bfd.h>
#include <stdio.h>
int main(int argc, char **argv) {
  if (argc != 2)
    return 1;
  bfd_init();
  bfd *b = bfd_openr(argv[1], NULL);
  if (!b)
    return 2;
  int ok = bfd_check_format(b, bfd_object) && (bfd_get_file_flags(b) & EXEC_P);
  bfd_close(b);
  return !ok;
}
