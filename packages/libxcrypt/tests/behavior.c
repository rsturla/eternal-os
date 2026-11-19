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
#include <crypt.h>
int main(void) {
  struct crypt_data data = {0};
  char saved[256];
  char *hash = crypt_r("correct horse", "$6$eternal$", &data);
  CHECK(hash && hash[0] != '*');
  /* Independent OpenSSL oracle: openssl passwd -6 -salt eternal 'correct
   * horse'. */
  CHECK(!strcmp(hash,
                "$6$eternal$ds463OEgEeK9yanfwLn/d7QLtihZ./zonI33ygZTq6qUJ8zt"
                "RzIrlLDRfFgLjBg7m9MeCFmUTi0jRwg.jP/s90"));
  CHECK(strlen(hash) < sizeof saved);
  strcpy(saved, hash);
  hash = crypt_r("correct horse", saved, &data);
  CHECK(hash && !strcmp(hash, saved));
  hash = crypt_r("wrong password", saved, &data);
  CHECK(hash && strcmp(hash, saved));
  hash = crypt_r("password", "$unsupported$", &data);
  CHECK(!hash || hash[0] == '*');
  char entropy[32] = "deterministic fixture entropy";
  char salt[CRYPT_GENSALT_OUTPUT_SIZE];
  CHECK(crypt_gensalt_rn("$y$", 0, entropy, sizeof entropy, salt, sizeof salt));
  CHECK(!strncmp(salt, "$y$", 3));
  hash = crypt_r("correct horse", salt, &data);
  CHECK(hash && !strncmp(hash, "$y$", 3));
  CHECK(strlen(hash) < sizeof saved);
  strcpy(saved, hash);
  hash = crypt_r("correct horse", saved, &data);
  CHECK(hash && !strcmp(hash, saved));
  hash = crypt_r("wrong password", saved, &data);
  CHECK(hash && strcmp(hash, saved));
  return 0;
}
