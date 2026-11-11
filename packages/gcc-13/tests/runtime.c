#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static _Thread_local int tls;
static atomic_int count;
static void *worker(void *p) {
  tls = 7;
  for (int i = 0; i < 10000; i++)
    atomic_fetch_add(&count, 1);
  return (void *)(intptr_t)(tls + *(int *)p);
}
int main(void) {
  int x = 35;
  pthread_t threads[4];
  for (int i = 0; i < 4; i++)
    assert(pthread_create(&threads[i], 0, worker, &x) == 0);
  for (int i = 0; i < 4; i++) {
    void *result;
    assert(pthread_join(threads[i], &result) == 0);
    assert((intptr_t)result == 42);
  }
  assert(count == 40000 && tls == 0);
  unsigned char *p = calloc(4096, 1);
  assert(p);
  for (int i = 0; i < 4096; i++)
    assert(p[i] == 0);
  free(p);
  char s[64];
  assert(snprintf(s, sizeof s, "%d:%s", 42, "test") == 7);
  assert(!strcmp(s, "42:test"));
  errno = 0;
  char *end;
  assert(strtol("123x", &end, 10) == 123 && *end == 'x');
  puts("c-runtime-ok");
  return 0;
}
