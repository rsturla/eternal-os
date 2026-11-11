import ctypes as C

l = C.CDLL("libsmartcols.so.1")
l.scols_new_table.restype = C.c_void_p
l.scols_table_new_column.argtypes = [C.c_void_p, C.c_char_p, C.c_double, C.c_int]
l.scols_table_new_column.restype = C.c_void_p
l.scols_table_new_line.argtypes = [C.c_void_p, C.c_void_p]
l.scols_table_new_line.restype = C.c_void_p
l.scols_line_set_data.argtypes = [C.c_void_p, C.c_size_t, C.c_char_p]
l.scols_table_get_nlines.argtypes = [C.c_void_p]
l.scols_unref_table.argtypes = [C.c_void_p]
p = l.scols_new_table()
assert p and l.scols_table_new_column(p, b"NAME", 0, 0)
a = l.scols_table_new_line(p, None)
assert (
    a
    and l.scols_line_set_data(a, 0, b"fixture") == 0
    and l.scols_table_get_nlines(p) == 1
)
l.scols_unref_table(p)
