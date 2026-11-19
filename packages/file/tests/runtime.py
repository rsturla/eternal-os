import ctypes as C

l = C.CDLL("libmagic.so.1")
l.magic_open.argtypes = [C.c_int]
l.magic_open.restype = C.c_void_p
l.magic_load.argtypes = [C.c_void_p, C.c_char_p]
l.magic_buffer.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
l.magic_buffer.restype = C.c_char_p
l.magic_close.argtypes = [C.c_void_p]
m = l.magic_open(0x10)
assert m and l.magic_load(m, None) == 0
assert l.magic_buffer(m, b"plain text\n", 11) == b"text/plain"
l.magic_close(m)
