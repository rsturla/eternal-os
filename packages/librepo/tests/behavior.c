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
#include <librepo/librepo.h>
int main(int argc, char **argv) {
  CHECK(argc == 2);
  LrHandle *handle = lr_handle_init();
  CHECK(handle);
  GError *error = NULL;
  CHECK(lr_handle_setopt(handle, &error, LRO_REPOTYPE, LR_YUMREPO));
  LrResult *result = lr_result_init();
  CHECK(result);
  CHECK(!lr_handle_perform(handle, result, &error));
  CHECK(error != NULL);
  g_clear_error(&error);
  lr_result_free(result);
  result = lr_result_init();
  CHECK(result);
  char *urls[] = {argv[1], NULL};
  CHECK(lr_handle_setopt(handle, &error, LRO_URLS, urls));
  CHECK(lr_handle_setopt(handle, &error, LRO_LOCAL, 1L));
  CHECK(lr_handle_setopt(handle, &error, LRO_CHECKSUM, 1L));
  CHECK(lr_handle_perform(handle, result, &error));
  CHECK(error == NULL);
  LrYumRepo *repository = NULL;
  CHECK(lr_result_getinfo(result, &error, LRR_YUM_REPO, &repository));
  CHECK(repository);
  const char *primary = lr_yum_repo_path(repository, "primary");
  CHECK(primary && strstr(primary, "primary.xml"));
  CHECK(lr_yum_repo_path(repository, "missing") == NULL);
  lr_result_free(result);
  lr_handle_free(handle);

  /* A well-formed primary file with different bytes must fail its manifest
     checksum. A fresh handle/result prevents the valid fetch masking this. */
  gchar *metadata = NULL;
  gsize size = 0;
  char *path = g_build_filename(argv[1], "repodata", "primary.xml", NULL);
  CHECK(g_file_get_contents(path, &metadata, &size, &error));
  char *count = strstr(metadata, "packages=\"0\"");
  CHECK(count);
  count[strlen("packages=\"")] = '1';
  CHECK(g_file_set_contents(path, metadata, size, &error));
  g_free(metadata);
  g_free(path);
  handle = lr_handle_init();
  result = lr_result_init();
  CHECK(handle && result);
  CHECK(lr_handle_setopt(handle, &error, LRO_REPOTYPE, LR_YUMREPO));
  CHECK(lr_handle_setopt(handle, &error, LRO_URLS, urls));
  CHECK(lr_handle_setopt(handle, &error, LRO_LOCAL, 1L));
  CHECK(lr_handle_setopt(handle, &error, LRO_CHECKSUM, 1L));
  CHECK(!lr_handle_perform(handle, result, &error));
  CHECK(error && error->code == LRE_BADCHECKSUM);
  g_clear_error(&error);
  lr_result_free(result);
  lr_handle_free(handle);
  return 0;
}
