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
#include <security/pam_appl.h>
static int converse(int n, const struct pam_message **m,
                    struct pam_response **r, void *data) {
  (void)n;
  (void)m;
  (void)r;
  (void)data;
  return PAM_CONV_ERR;
}
int main(void) {
  CHECK(pam_strerror(NULL, PAM_SUCCESS) != NULL);
  FILE *config = fopen("fixture", "w");
  CHECK(config);
  CHECK(fputs("auth required pam_deny.so\n", config) >= 0);
  CHECK(fclose(config) == 0);
  char directory[4096];
  CHECK(getcwd(directory, sizeof directory));
  pam_handle_t *h = NULL;
  struct pam_conv conversation = {converse, NULL};
  CHECK(pam_start_confdir("fixture", "eternal-user", &conversation, directory, &h) ==
        PAM_SUCCESS);
  const void *value = NULL;
  CHECK(pam_get_item(h, PAM_USER, &value) == PAM_SUCCESS &&
        !strcmp(value, "eternal-user"));
  CHECK(pam_set_item(h, PAM_TTY, "fixture-tty") == PAM_SUCCESS);
  CHECK(pam_get_item(h, PAM_TTY, &value) == PAM_SUCCESS &&
        !strcmp(value, "fixture-tty"));
  CHECK(pam_end(h, PAM_SUCCESS) == PAM_SUCCESS);
  return 0;
}
