import ctypes as C

l = C.CDLL("libpkgconf.so.8")
l.pkgconf_compare_version.argtypes = [C.c_char_p, C.c_char_p]
assert l.pkgconf_compare_version(b"1.2.3", b"1.2.3") == 0
assert l.pkgconf_compare_version(b"2.0", b"1.9") > 0
assert l.pkgconf_compare_version(b"1.0", b"1.1") < 0
