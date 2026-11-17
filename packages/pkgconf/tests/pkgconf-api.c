#include <libpkgconf/libpkgconf.h>
int main(void) {
  if (pkgconf_compare_version("1.2.3", "1.2.3") != 0)
    return 1;
  if (pkgconf_compare_version("2.0", "1.9") <= 0)
    return 2;
  return pkgconf_compare_version("1.0", "1.1") >= 0;
}
