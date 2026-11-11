import ctypes as C

l = C.CDLL("libattr.so.1")
open("target", "wb").close()
l.attr_set.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.c_int, C.c_int]
l.attr_get.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.POINTER(C.c_int), C.c_int]
assert l.attr_set(b"target", b"eternal", b"value", 5, 0) == 0
b = C.create_string_buffer(32)
n = C.c_int(32)
assert (
    l.attr_get(b"target", b"eternal", b, C.byref(n), 0) == 0
    and b.raw[: n.value] == b"value"
)
assert l.attr_remove(b"target", b"eternal", 0) == 0
