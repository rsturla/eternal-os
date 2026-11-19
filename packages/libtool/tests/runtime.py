import ctypes as C

l = C.CDLL("libltdl.so.7")
l.lt_dlopen.argtypes = [C.c_char_p]
l.lt_dlopen.restype = C.c_void_p
l.lt_dlsym.argtypes = [C.c_void_p, C.c_char_p]
l.lt_dlsym.restype = C.c_void_p
l.lt_dlclose.argtypes = [C.c_void_p]
l.lt_dlisresident.argtypes = [C.c_void_p]
assert l.lt_dlinit() == 0
h = l.lt_dlopen(None)
assert h and l.lt_dlsym(h, b"printf")
# A resident process handle must not be unloaded, so close reports an error.
assert l.lt_dlisresident(h) == 1 and l.lt_dlclose(h) != 0
assert l.lt_dlexit() == 0
