#include <rpm/rpmlib.h>
#include <rpm/rpmmacro.h>
#include <rpm/rpmts.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
  if (rpmReadConfigFiles(NULL, NULL))
    return 1;
  char *value = rpmExpand("%{_prefix}", NULL);
  int failed = !value || strcmp(value, "/usr");
  free(value);
  rpmts ts = rpmtsCreate();
  if (!ts)
    return 2;
  rpmtsFree(ts);
  return failed;
}
