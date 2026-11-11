#include <auparse.h>
#include <libaudit.h>
#include <string.h>
int main(void) {
  if (audit_name_to_msg_type("SYSCALL") != AUDIT_SYSCALL)
    return 1;
  if (strcmp(audit_msg_type_to_name(AUDIT_SYSCALL), "SYSCALL"))
    return 2;
  if (audit_name_to_msg_type("NO_SUCH_TYPE") != -1)
    return 3;
  const char *record = "type=SYSCALL msg=audit(1700000000.001:7): "
                       "arch=c000003e syscall=59 success=yes exit=0 uid=1000\n";
  auparse_state_t *a = auparse_init(AUSOURCE_BUFFER, record);
  if (!a)
    return 4;
  if (auparse_next_event(a) != 1 || auparse_get_type(a) != AUDIT_SYSCALL)
    return 5;
  const char *uid = auparse_find_field(a, "uid");
  int result = !uid || strcmp(uid, "1000");
  auparse_destroy(a);
  return result;
}
