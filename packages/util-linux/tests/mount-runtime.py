import ctypes as C

l = C.CDLL("libmount.so.1")
l.mnt_new_table.restype = C.c_void_p
l.mnt_new_fs.restype = C.c_void_p
for n in ["mnt_unref_table", "mnt_unref_fs", "mnt_table_get_nents"]:
    getattr(l, n).argtypes = [C.c_void_p]
l.mnt_fs_set_target.argtypes = [C.c_void_p, C.c_char_p]
l.mnt_table_add_fs.argtypes = [C.c_void_p, C.c_void_p]
t = l.mnt_new_table()
f = l.mnt_new_fs()
assert t and f
assert (
    l.mnt_fs_set_target(f, b"/fixture") == 0
    and l.mnt_table_add_fs(t, f) == 0
    and l.mnt_table_get_nents(t) == 1
)
l.mnt_unref_fs(f)
l.mnt_unref_table(t)
