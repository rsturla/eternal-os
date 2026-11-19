import ctypes as C

l = C.CDLL("libzck.so.1")
l.zck_create.restype = C.c_void_p
l.zck_free.argtypes = [C.POINTER(C.c_void_p)]
p = C.c_void_p(l.zck_create())
assert p.value
l.zck_free(C.byref(p))
assert not p.value
