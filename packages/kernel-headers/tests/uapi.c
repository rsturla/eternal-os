#include <asm/unistd.h>
#include <linux/fs.h>
#include <linux/futex.h>
#include <linux/if_tun.h>
#include <linux/input.h>
#include <linux/ioctl.h>
#include <linux/netlink.h>
#include <linux/rtnetlink.h>
#include <linux/seccomp.h>
#include <linux/socket.h>
#include <linux/types.h>
#include <stddef.h>
_Static_assert(sizeof(__u64) == 8, "u64 ABI");
_Static_assert(sizeof(__u32) == 4, "u32 ABI");
_Static_assert(sizeof(struct nlmsghdr) == 16, "netlink ABI");
_Static_assert(offsetof(struct nlmsghdr, nlmsg_pid) == 12, "netlink offset");
_Static_assert(_IOC_TYPE(FS_IOC_GETFLAGS) == 'f', "filesystem ioctl ABI");
_Static_assert(FUTEX_WAIT == 0, "futex ABI");
_Static_assert(__NR_read >= 0, "syscall table");
int main(void) { return 0; }
