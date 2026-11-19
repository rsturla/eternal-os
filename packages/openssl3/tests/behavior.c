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
#include <openssl/evp.h>
#include <openssl/comp.h>
#include <openssl/objects.h>
#include <openssl/ssl.h>
int main(void) {
  const unsigned char expected[] = {
      0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40,
      0xde, 0x5d, 0xae, 0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17,
      0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
  unsigned char digest[EVP_MAX_MD_SIZE];
  unsigned int size = 0;
  CHECK(EVP_Digest("abc", 3, digest, &size, EVP_sha256(), NULL) == 1);
  CHECK(size == 32 && !memcmp(digest, expected, 32));
  EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
  CHECK(ctx);
  unsigned char key[32] = {0}, iv[12] = {0}, encrypted[32], plain[32], tag[16];
  int length, total;
  CHECK(EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, key, iv) == 1);
  CHECK(EVP_EncryptUpdate(ctx, encrypted, &length,
                          (const unsigned char *)"payload", 7) == 1);
  total = length;
  CHECK(EVP_EncryptFinal_ex(ctx, encrypted + total, &length) == 1);
  total += length;
  CHECK(EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, 16, tag) == 1);
  CHECK(EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, key, iv) == 1);
  CHECK(EVP_DecryptUpdate(ctx, plain, &length, encrypted, total) == 1);
  CHECK(length == 7 && !memcmp(plain, "payload", 7));
  CHECK(EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, 16, tag) == 1);
  CHECK(EVP_DecryptFinal_ex(ctx, plain + length, &total) == 1);
  tag[0] ^= 1;
  CHECK(EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, key, iv) == 1);
  CHECK(EVP_DecryptUpdate(ctx, plain, &length, encrypted, 7) == 1);
  CHECK(EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, 16, tag) == 1);
  CHECK(EVP_DecryptFinal_ex(ctx, plain + length, &total) == 0);
  EVP_CIPHER_CTX_free(ctx);
  /* Keep the public COMP ABI while leaving compression unavailable. */
  CHECK(COMP_get_type(NULL) == NID_undef);
  CHECK(COMP_get_name(NULL) == NULL);
  CHECK(COMP_zlib() == NULL);
  SSL_CTX *tls = SSL_CTX_new(TLS_method());
  CHECK(tls);
  CHECK(SSL_CTX_set_min_proto_version(tls, TLS1_2_VERSION) == 1);
  SSL_CTX_free(tls);
  return 0;
}
