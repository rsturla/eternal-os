import ctypes as C

l = C.CDLL("libfdisk.so.1")
l.fdisk_new_context.restype = C.c_void_p
l.fdisk_unref_context.argtypes = [C.c_void_p]
l.fdisk_get_nlabels.argtypes = [C.c_void_p]
l.fdisk_get_nlabels.restype = C.c_size_t
p = l.fdisk_new_context()
assert p and l.fdisk_get_nlabels(p) > 0
l.fdisk_unref_context(p)
