"""Exercise the public OpenSSL ABI used by a separately built Python extension."""

import ctypes
import ssl

# Importing ssl must resolve the versioned COMP_* symbols required by _ssl.
# Removing the API with no-comp broke consumers even with TLS compression off.
crypto = ctypes.CDLL("libcrypto.so.3")
crypto.COMP_get_type.argtypes = [ctypes.c_void_p]
crypto.COMP_get_type.restype = ctypes.c_int
crypto.COMP_get_name.argtypes = [ctypes.c_void_p]
crypto.COMP_get_name.restype = ctypes.c_char_p
crypto.COMP_zlib.argtypes = []
crypto.COMP_zlib.restype = ctypes.c_void_p
assert crypto.COMP_get_type(None) == 0, "COMP_get_type(NULL) must return NID_undef"
assert crypto.COMP_get_name(None) is None, "COMP_get_name(NULL) must return NULL"
assert crypto.COMP_zlib() is None, "zlib compression must remain unavailable"

context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
assert ssl.OPENSSL_VERSION_INFO[:2] == (3, 5), ssl.OPENSSL_VERSION
assert context.check_hostname, "TLS clients must check hostnames by default"
assert context.verify_mode == ssl.CERT_REQUIRED, "TLS clients must verify certificates"
assert context.options & ssl.OP_NO_COMPRESSION, "TLS compression must remain disabled"
print(f"Python ssl loaded {ssl.OPENSSL_VERSION}; public COMP API and safe TLS defaults pass")
