import ctypes as C

l = C.CDLL("libuuid.so.1")
a = C.create_string_buffer(16)
b = C.create_string_buffer(16)
text = C.create_string_buffer(37)
l.uuid_generate(a)
l.uuid_unparse(a, text)
assert len(text.value) == 36
assert l.uuid_parse(text, b) == 0 and l.uuid_compare(a, b) == 0
assert l.uuid_parse(b"invalid", b) != 0
