import asyncio
import bz2
import ctypes
import decimal
import hashlib
import json
import lzma
import pathlib
import pickle
import readline
import socket
import sqlite3
import ssl
import subprocess
import sys
import sysconfig
import tempfile
import threading
import unicodedata
import xml.etree.ElementTree as ET
import zlib

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert sysconfig.get_paths()["stdlib"] == "/usr/lib/python" + sys.argv[1]
payload = bytes(range(256)) * 100
for compress, decompress in [
    (bz2.compress, bz2.decompress),
    (lzma.compress, lzma.decompress),
    (zlib.compress, zlib.decompress),
]:
    assert decompress(compress(payload)) == payload
    try:
        decompress(b"not a compressed stream")
    except (ValueError, EOFError, OSError, zlib.error, lzma.LZMAError):
        pass
    else:
        raise AssertionError("malformed input accepted")
assert (
    hashlib.sha256(b"abc").hexdigest()
    == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
)
assert decimal.Decimal("0.1") + decimal.Decimal("0.2") == decimal.Decimal("0.3")
assert unicodedata.normalize("NFC", "e\u0301") == "\u00e9"
obj = {"unicode": "\u2603", "values": [None, True, 42]}
assert pickle.loads(pickle.dumps(obj)) == json.loads(json.dumps(obj)) == obj
assert ET.fromstring("<root><child>42</child></root>").findtext("child") == "42"
with sqlite3.connect(":memory:") as db:
    db.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT UNIQUE)")
    db.execute("INSERT INTO example(value) VALUES (?)", ("payload",))
    assert db.execute("SELECT value FROM example").fetchone() == ("payload",)
    try:
        db.execute("INSERT INTO example(value) VALUES (?)", ("payload",))
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("SQLite uniqueness lost")
readline.clear_history()
readline.add_history("rpmx probe")
assert readline.get_history_item(1) == "rpmx probe"
readline.clear_history()
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    with socket.create_connection(listener.getsockname(), timeout=5) as client:
        accepted, _ = listener.accept()
        with accepted:
            accepted.settimeout(5)
            client.sendall(b"loopback")
            with accepted.makefile("rb") as incoming:
                assert incoming.read(8) == b"loopback"
assert ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).verify_mode == ssl.CERT_REQUIRED
libc = ctypes.CDLL(None)
libc.strlen.argtypes = [ctypes.c_char_p]
libc.strlen.restype = ctypes.c_size_t
assert libc.strlen(b"hello") == 5
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / "payload"
    p.write_bytes(payload)
    assert p.read_bytes() == payload
assert (
    subprocess.check_output([sys.executable, "-I", "-c", "print(6*7)"], text=True)
    == "42\n"
)
result = []
t = threading.Thread(target=lambda: result.append(42))
t.start()
t.join()
assert result == [42]


async def probe():
    await asyncio.sleep(0)
    return 42


assert asyncio.run(probe()) == 42
print("python-runtime-ok")
