import ctypes as C

l = C.CDLL("libaudit.so.1")
l.audit_name_to_msg_type.argtypes = [C.c_char_p]
assert l.audit_name_to_msg_type(b"SYSCALL") == 1300
assert l.audit_name_to_msg_type(b"NO_SUCH_TYPE") == -1
p = C.CDLL("libauparse.so.0")
p.auparse_init.argtypes = [C.c_int, C.c_char_p]
p.auparse_init.restype = C.c_void_p
p.auparse_next_event.argtypes = [C.c_void_p]
p.auparse_get_type.argtypes = [C.c_void_p]
p.auparse_destroy.argtypes = [C.c_void_p]
a = p.auparse_init(
    3, b"type=SYSCALL msg=audit(1700000000.001:7): syscall=59 uid=1000\n"
)
assert a and p.auparse_next_event(a) == 1 and p.auparse_get_type(a) == 1300
p.auparse_destroy(a)
