import ctypes as C

l = C.CDLL("liblzma.so.5")
l.lzma_easy_buffer_encode.argtypes = [
    C.c_uint32,
    C.c_int,
    C.c_void_p,
    C.c_void_p,
    C.c_size_t,
    C.c_void_p,
    C.POINTER(C.c_size_t),
    C.c_size_t,
]
l.lzma_stream_buffer_decode.argtypes = [
    C.POINTER(C.c_uint64),
    C.c_uint32,
    C.c_void_p,
    C.c_void_p,
    C.POINTER(C.c_size_t),
    C.c_size_t,
    C.c_void_p,
    C.POINTER(C.c_size_t),
    C.c_size_t,
]
data = b"binary\0payload" * 100
packed = C.create_string_buffer(4096)
out = C.create_string_buffer(4096)
n = C.c_size_t()
assert (
    l.lzma_easy_buffer_encode(6, 4, None, data, len(data), packed, C.byref(n), 4096)
    == 0
)
limit = C.c_uint64(2**64 - 1)
i = C.c_size_t()
m = C.c_size_t()
assert (
    l.lzma_stream_buffer_decode(
        C.byref(limit), 0, None, packed, C.byref(i), n.value, out, C.byref(m), 4096
    )
    == 0
)
assert out.raw[: m.value] == data
