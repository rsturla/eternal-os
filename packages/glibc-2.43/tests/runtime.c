#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <gnu/libc-version.h>
#include <iconv.h>
#include <locale.h>
#include <math.h>
#include <pthread.h>
#include <regex.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static _Thread_local int local;
static void *run(void *p) {
  (void)p;
  local = 42;
  return &local;
}
int main(void) {
  pthread_t t;
  assert(pthread_create(&t, 0, run, 0) == 0);
  assert(pthread_join(t, 0) == 0);
  assert(local == 0);
  char b[8];
  assert(strlcpy(b, "abc", sizeof b) == 3 && !strcmp(b, "abc"));
  char *p = calloc(4096, 1);
  assert(p);
  for (int i = 0; i < 4096; i++)
    assert(!p[i]);
  free(p);
  p = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  assert(p != MAP_FAILED);
  strcpy(p, "mapped");
  assert(!strcmp(p, "mapped"));
  assert(!munmap(p, 4096));
  regex_t re;
  assert(!regcomp(&re, "^a[0-9]+$", REG_EXTENDED));
  assert(!regexec(&re, "a123", 0, 0, 0));
  assert(regexec(&re, "b123", 0, 0, 0) == REG_NOMATCH);
  regfree(&re);
  assert(setlocale(LC_ALL, "C"));
  volatile double x = 2.0;
  assert(fabs(log(exp(x)) - 2.0) < 1e-9);
  errno = 0;
  assert(close(-1) == -1 && errno == EBADF);
  puts(gnu_get_libc_version());
  return 0;
}
