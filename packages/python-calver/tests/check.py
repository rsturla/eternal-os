import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
from calver.integration import version
from types import SimpleNamespace


def resolve(value):
    distribution = SimpleNamespace(metadata=SimpleNamespace(version=None))
    version(distribution, "use_calver", value)
    return distribution.metadata.version


for epoch, expected in [
    ("0", "1970.01.01"),
    ("86400", "1970.01.02"),
    ("951782400", "2000.02.29"),
]:
    os.environ["SOURCE_DATE_EPOCH"] = epoch
    assert resolve(True) == expected
os.environ["SOURCE_DATE_EPOCH"] = "0"
assert resolve("%Y.%m") == "1970.01"
assert resolve(lambda: "4.2") == "4.2"
assert resolve(False) is None
Path("PKG-INFO").write_text("Metadata-Version: 2.1\nName: fixture\nVersion: 2.3.4\n")
assert resolve(True) == "2.3.4"
Path("PKG-INFO").unlink()
os.environ["SOURCE_DATE_EPOCH"] = "not-an-epoch"
try:
    resolve(True)
except ValueError:
    pass
else:
    raise AssertionError("invalid SOURCE_DATE_EPOCH accepted")
