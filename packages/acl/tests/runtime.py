import ctypes as C

l = C.CDLL("libacl.so.1")
l.acl_from_text.argtypes = [C.c_char_p]
l.acl_from_text.restype = C.c_void_p
l.acl_valid.argtypes = [C.c_void_p]
l.acl_free.argtypes = [C.c_void_p]
a = l.acl_from_text(b"u::rw-,g::r--,o::---")
assert a and l.acl_valid(a) == 0
assert l.acl_free(a) == 0
assert not l.acl_from_text(b"invalid")
