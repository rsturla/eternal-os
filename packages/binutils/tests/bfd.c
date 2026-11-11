#define PACKAGE "eternal-bfd-probe"
#include <bfd.h>
#include <stdio.h>

int main(int argc, char **argv) {
  if (argc != 2) {
    fprintf(stderr, "usage: %s EXECUTABLE\n", argv[0]);
    return 1;
  }
  bfd_init();
  bfd *binary = bfd_openr(argv[1], NULL);
  if (!binary) {
    fprintf(stderr, "cannot open %s: %s\n", argv[1], bfd_errmsg(bfd_get_error()));
    return 1;
  }
  if (!bfd_check_format(binary, bfd_object)) {
    fprintf(stderr, "%s is not an object: %s\n", argv[1], bfd_errmsg(bfd_get_error()));
    bfd_close(binary);
    return 1;
  }
  /* PIE executables have DYNAMIC rather than EXEC_P in BFD's file flags. */
  flagword flags = bfd_get_file_flags(binary);
  asection *text = bfd_get_section_by_name(binary, ".text");
  int executable = (flags & (EXEC_P | DYNAMIC)) &&
                   bfd_get_start_address(binary) != 0 && text &&
                   (bfd_section_flags(text) & (SEC_ALLOC | SEC_CODE)) ==
                       (SEC_ALLOC | SEC_CODE) &&
                   bfd_section_size(text) > 0;
  if (!executable)
    fprintf(stderr, "%s has no executable entry point and code section\n", argv[1]);
  if (!bfd_close(binary)) {
    fprintf(stderr, "cannot close %s: %s\n", argv[1], bfd_errmsg(bfd_get_error()));
    return 1;
  }
  return !executable;
}
