import ctypes as C

l = C.CDLL("libblkid.so.1")
l.blkid_new_probe.restype = C.c_void_p
l.blkid_free_probe.argtypes = [C.c_void_p]
l.blkid_encode_string.argtypes = [C.c_char_p, C.c_void_p, C.c_size_t]
p = l.blkid_new_probe()
assert p
l.blkid_free_probe(p)
out = C.create_string_buffer(64)
assert (
    l.blkid_encode_string(b"with space", out, 64) == 0
    and out.value == b"with\\x20space"
)
