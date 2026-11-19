#include <security/pam_appl.h>
#include <stdio.h>
#include <string.h>

#define CHECK(expr)                                                            \
  do {                                                                         \
    if (!(expr)) {                                                             \
      fprintf(stderr, "%s:%d: %s failed\n", __FILE__, __LINE__, #expr);        \
      return 1;                                                                \
    }                                                                          \
  } while (0)

static int converse(int count, const struct pam_message **messages,
                    struct pam_response **responses, void *data) {
  (void)count;
  (void)messages;
  (void)responses;
  (void)data;
  return PAM_CONV_ERR;
}

int main(int argc, char **argv) {
  CHECK(argc == 3);
  const struct pam_conv conversation = {converse, NULL};
  pam_handle_t *handle = NULL;
  CHECK(pam_start_confdir(argv[2], "eternal-fixture-user", &conversation,
                          argv[1], &handle) == PAM_SUCCESS);
  int expected = !strcmp(argv[2], "permit") ? PAM_SUCCESS : PAM_AUTH_ERR;
  int status = pam_authenticate(handle, 0);
  CHECK(status == expected);
  if (expected == PAM_SUCCESS) {
    CHECK(pam_acct_mgmt(handle, 0) == PAM_SUCCESS);
  }
  CHECK(pam_end(handle, status) == PAM_SUCCESS);
  return 0;
}
