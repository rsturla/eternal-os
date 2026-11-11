#include <ltdl.h>
int main(void) {
  if (lt_dlinit())
    return 1;
  lt_dlhandle h = lt_dlopen(0);
  if (!h)
    return 2;
  if (!lt_dlsym(h, "printf"))
    return 3;
  /* The process handle is resident; libltdl must reject a request to close it. */
  if (!lt_dlisresident(h) || !lt_dlclose(h))
    return 4;
  return lt_dlexit();
}
