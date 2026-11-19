#include <curl/curl.h>
#include <stdio.h>
#include <string.h>
static char data[64];
static size_t used;
static size_t receive(char *ptr, size_t size, size_t nmemb, void *arg) {
  (void)arg;
  size_t n = size * nmemb;
  if (used + n > sizeof data)
    return 0;
  memcpy(data + used, ptr, n);
  used += n;
  return n;
}
int main(int argc, char **argv) {
  if (argc != 2 || curl_global_init(CURL_GLOBAL_DEFAULT))
    return 1;
  CURL *c = curl_easy_init();
  if (!c)
    return 2;
  curl_easy_setopt(c, CURLOPT_URL, argv[1]);
  curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, receive);
  CURLcode result = curl_easy_perform(c);
  curl_easy_cleanup(c);
  curl_global_cleanup();
  return result != CURLE_OK || used != 8 || memcmp(data, "payload\n", 8);
}
