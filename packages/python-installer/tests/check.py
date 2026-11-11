import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
from installer import install
from installer.destinations import SchemeDictionaryDestination
from installer.sources import WheelFile
from installer.utils import parse_entrypoints
import base64
import csv
import hashlib
import runpy
import subprocess

make_wheel = runpy.run_path(str(fixtures / "wheel_fixture.py"))["wheel"]
archive = make_wheel("wheels")
prefix = Path("prefix").resolve()
scheme = {
    "purelib": str(prefix / "lib"),
    "platlib": str(prefix / "lib"),
    "headers": str(prefix / "include"),
    "scripts": str(prefix / "bin"),
    "data": str(prefix),
}
destination = SchemeDictionaryDestination(
    scheme,
    interpreter=sys.executable,
    script_kind="posix",
    bytecode_optimization_levels=[0],
)
with WheelFile.open(archive) as source:
    source.validate_record(validate_contents=True)
    install(source, destination, additional_metadata={"INSTALLER": b"eternal-test\n"})
assert (prefix / "lib/eternal_fixture/__init__.py").is_file()
assert list((prefix / "lib/eternal_fixture/__pycache__").glob("*.pyc"))
assert (
    prefix / "lib/eternal_fixture-1.0.dist-info/INSTALLER"
).read_text() == "eternal-test\n"
script = prefix / "bin/eternal-fixture"
assert script.is_file() and os.access(script, os.X_OK)
assert script.read_text().splitlines()[0] == "#!" + sys.executable
# Execute the installed script itself so its shebang and selected interpreter
# matter. Only this temporary installation supplies its fixture module.
launched = subprocess.run(
    [str(script)],
    env={**os.environ, "PYTHONPATH": str(prefix / "lib")},
    check=True,
    capture_output=True,
    text=True,
)
assert launched.stdout == "fixture-cli-ok\n"
subprocess.run(
    [
        sys.executable,
        "-I",
        "-c",
        "import sys;sys.path.insert(0,sys.argv[1]);import eternal_fixture;assert eternal_fixture.ANSWER==42",
        str(prefix / "lib"),
    ],
    check=True,
)
records = list(
    csv.reader(
        (prefix / "lib/eternal_fixture-1.0.dist-info/RECORD").read_text().splitlines()
    )
)
assert records and any(row[0].endswith("eternal-fixture") for row in records)
for relative, digest, size in records:
    path = prefix / "lib" / relative
    if digest:
        data = path.read_bytes()
        actual = (
            base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            .rstrip(b"=")
            .decode()
        )
        assert digest == "sha256=" + actual and int(size) == len(data), relative
assert list(
    parse_entrypoints("[console_scripts]\nprobe = eternal_fixture.cli:main\n")
) == [("probe", "eternal_fixture.cli", "main", "console")]
# Reject a wheel whose payload has changed since RECORD was written.
import zipfile

Path("corrupted").mkdir()
bad = Path("corrupted") / archive.name
with zipfile.ZipFile(archive) as source, zipfile.ZipFile(bad, "w") as target:
    for name in source.namelist():
        target.writestr(
            name, b"corrupt" if name.endswith("__init__.py") else source.read(name)
        )
try:
    with WheelFile.open(bad) as source:
        source.validate_record(validate_contents=True)
except ValueError as error:
    assert "__init__.py" in str(error), error
else:
    raise AssertionError("corrupted wheel accepted")
