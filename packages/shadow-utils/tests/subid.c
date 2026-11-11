#include <assert.h>
#include <shadow/subid.h>

int main(void) {
  assert(subid_init("rpmx-test", stderr));
  struct subid_range *ranges = NULL;
  assert(subid_get_uid_ranges("24567", &ranges) == 2);
  int first = 0, second = 0;
  for (int i = 0; i < 2; i++) {
    first += ranges[i].start == 200000 && ranges[i].count == 100;
    second += ranges[i].start == 300000 && ranges[i].count == 200;
  }
  assert(first == 1 && second == 1);
  subid_free(ranges);
  ranges = NULL;
  assert(subid_get_gid_ranges("24567", &ranges) == 1);
  assert(ranges[0].start == 500000 && ranges[0].count == 50);
  subid_free(ranges);
  ranges = NULL;
  assert(subid_get_uid_ranges("24568", &ranges) == 0);
  subid_free(ranges);

  uid_t *owners = NULL;
  assert(subid_get_uid_owners(200000, &owners) == 1);
  assert(owners[0] == 24567);
  subid_free(owners);
  owners = NULL;
  assert(subid_get_uid_owners(200100, &owners) == 0);
  subid_free(owners);
  owners = NULL;
  assert(subid_get_gid_owners(500049, &owners) == 1);
  assert(owners[0] == 24567);
  subid_free(owners);
  return 0;
}
