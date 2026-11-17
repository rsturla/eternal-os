#include <gnumake.h>
#include <string.h>

int plugin_is_GPL_compatible;

static char *fixture(const char *name, unsigned int argc, char **argv) {
  (void)name;
  (void)argc;
  (void)argv;
  char *result = gmk_alloc(3);
  memcpy(result, "42", 3);
  return result;
}

int eternal_gmk_setup(void) {
  gmk_add_function("eternal", fixture, 0, 0, GMK_FUNC_DEFAULT);
  return 1;
}
