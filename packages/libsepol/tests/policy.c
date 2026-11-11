#include <sepol/cil/cil.h>
#include <sepol/policydb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(expr)                                                            \
  do {                                                                         \
    if (!(expr)) {                                                             \
      fprintf(stderr, "%s:%d: %s failed\n", __FILE__, __LINE__, #expr);        \
      return 1;                                                                \
    }                                                                          \
  } while (0)

int main(int argc, char **argv) {
  CHECK(argc == 2);
  FILE *file = fopen(argv[1], "rb");
  CHECK(file);
  CHECK(fseek(file, 0, SEEK_END) == 0);
  long length = ftell(file);
  CHECK(length > 0);
  rewind(file);
  char *source = calloc((size_t)length + 1, 1);
  CHECK(source);
  CHECK(fread(source, 1, length, file) == (size_t)length);
  CHECK(fclose(file) == 0);
  cil_db_t *cil = NULL;
  cil_db_init(&cil);
  CHECK(cil);
  cil_set_mls(cil, 0);
  CHECK(cil_add_file(cil, "minimal.cil", source, length) == 0);
  free(source);
  CHECK(cil_compile(cil) == 0);
  sepol_policydb_t *policy = NULL;
  CHECK(cil_build_policydb(cil, &policy) == 0 && policy);
  cil_db_destroy(&cil);
  void *image = NULL;
  size_t size = 0;
  CHECK(sepol_policydb_to_image(NULL, policy, &image, &size) == 0);
  CHECK(image && size > 0);
  sepol_policydb_t *copy = NULL;
  CHECK(sepol_policydb_create(&copy) == 0);
  CHECK(sepol_policydb_from_image(NULL, image, size, copy) == 0);
  CHECK(!sepol_policydb_mls_enabled(copy));
  sepol_policydb_free(copy);
  sepol_policydb_free(policy);
  free(image);
  cil_db_init(&cil);
  CHECK(cil);
  const char invalid[] = "(unknown-keyword fixture)";
  CHECK(cil_add_file(cil, "invalid.cil", invalid, sizeof invalid - 1) == 0);
  CHECK(cil_compile(cil) != 0);
  cil_db_destroy(&cil);
  return 0;
}
