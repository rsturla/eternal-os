"""Initialize the installed library without the rpm CLI or development tools."""

import ctypes
import glob
import os
from pathlib import Path

assert not Path("/usr/bin/rpm").exists(), "rpm CLI masks the library-only closure"
paths = sorted(glob.glob("/usr/lib*/librpm.so.*"))
assert paths, "installed librpm SONAME is missing"
rpm = ctypes.CDLL(paths[0], mode=os.RTLD_NOW)
rpm.rpmReadConfigFiles.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
rpm.rpmReadConfigFiles.restype = ctypes.c_int
assert rpm.rpmReadConfigFiles(None, None) == 0, "cannot load default RPM configuration"

rpm.rpmExpand.argtypes = [ctypes.c_char_p]
rpm.rpmExpand.restype = ctypes.c_void_p
libc = ctypes.CDLL("libc.so.6")
libc.free.argtypes = [ctypes.c_void_p]
libc.free.restype = None


def expand(macro):
    pointer = rpm.rpmExpand(macro.encode(), None)
    assert pointer, f"macro expansion failed: {macro}"
    try:
        return ctypes.string_at(pointer).decode()
    finally:
        libc.free(pointer)


for macro, expected in {
    "%{_prefix}": "/usr",
    "%{_target_os}": "linux",
    "%{_target_cpu}": os.environ["RPMX_TARGET_ARCH"],
    "%{_db_backend}": "sqlite",
    "%{_dbpath}": "/usr/lib/sysimage/rpm",
    "%{expr:6*7}": "42",
}.items():
    actual = expand(macro)
    assert actual == expected, f"{macro}: expected {expected!r}, got {actual!r}"

rpm.rpmtsCreate.argtypes = []
rpm.rpmtsCreate.restype = ctypes.c_void_p
rpm.rpmtsFree.argtypes = [ctypes.c_void_p]
rpm.rpmtsFree.restype = ctypes.c_void_p
transaction = rpm.rpmtsCreate()
assert transaction, "cannot create transaction after loading RPM configuration"
assert rpm.rpmtsFree(transaction) is None, "transaction reference was not released"
