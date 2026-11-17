import ctypes as C

l = C.CDLL("libzstd.so.1")
l.ZSTD_compress.restype = C.c_size_t
l.ZSTD_decompress.restype = C.c_size_t
l.ZSTD_compress.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.c_int]
l.ZSTD_decompress.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t]
data = b"binary\0payload" * 100
packed = C.create_string_buffer(4096)
out = C.create_string_buffer(4096)
n = l.ZSTD_compress(packed, 4096, data, len(data), 3)
assert 0 < n < 4096
m = l.ZSTD_decompress(out, 4096, packed, n)
assert m == len(data) and out.raw[:m] == data
