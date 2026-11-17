import base64
import csv
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from wheel.wheelfile import WheelFile, WheelError


class WheelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "fixture_package-1.2.3-py3-none-any.whl"
        self.info = "fixture_package-1.2.3.dist-info"
        with WheelFile(self.path, "w") as wheel:
            wheel.writestr("fixture_package/__init__.py", b"ANSWER = 42\n")
            wheel.writestr("fixture_package/data.bin", b"binary\0payload\xff")
            wheel.writestr(
                self.info + "/METADATA",
                "Metadata-Version: 2.1\nName: fixture-package\nVersion: 1.2.3\n",
            )
            wheel.writestr(
                self.info + "/WHEEL",
                "Wheel-Version: 1.0\nGenerator: eternal-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
            )

    def test_records_have_independently_verified_hashes_and_sizes(self):
        with zipfile.ZipFile(self.path) as wheel:
            rows = list(
                csv.reader(io.StringIO(wheel.read(self.info + "/RECORD").decode()))
            )
            self.assertEqual({row[0] for row in rows}, set(wheel.namelist()))
            for name, digest, size in rows:
                if name.endswith("/RECORD"):
                    self.assertEqual((digest, size), ("", ""))
                    continue
                data = wheel.read(name)
                expected = (
                    base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                    .rstrip(b"=")
                    .decode()
                )
                self.assertEqual(digest, "sha256=" + expected)
                self.assertEqual(int(size), len(data))
        with WheelFile(self.path) as wheel:
            self.assertEqual(
                wheel.read("fixture_package/data.bin"), b"binary\0payload\xff"
            )

    def test_tampered_payload_is_rejected(self):
        replacement = self.root / "tampered" / self.path.name
        replacement.parent.mkdir()
        with (
            zipfile.ZipFile(self.path) as source,
            zipfile.ZipFile(replacement, "w") as target,
        ):
            for name in source.namelist():
                target.writestr(
                    name,
                    b"ANSWER = 0\n"
                    if name.endswith("__init__.py")
                    else source.read(name),
                )
        with (
            WheelFile(replacement) as wheel,
            self.assertRaisesRegex(WheelError, "Hash mismatch"),
        ):
            wheel.read("fixture_package/__init__.py")

    def test_unrecorded_payload_is_rejected(self):
        replacement = self.root / "unrecorded" / self.path.name
        replacement.parent.mkdir()
        with (
            zipfile.ZipFile(self.path) as source,
            zipfile.ZipFile(replacement, "w") as target,
        ):
            for name in source.namelist():
                target.writestr(name, source.read(name))
            target.writestr("unrecorded.py", b"unexpected = True\n")
        with (
            WheelFile(replacement) as wheel,
            self.assertRaisesRegex(WheelError, "No hash found"),
        ):
            wheel.read("unrecorded.py")

    def test_cli_unpack_pack_preserves_payload(self):
        unpacked = self.root / "unpacked"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "wheel",
                "unpack",
                str(self.path),
                "-d",
                str(unpacked),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stderr, "")
        project = unpacked / "fixture_package-1.2.3"
        self.assertEqual(
            (project / "fixture_package/data.bin").read_bytes(), b"binary\0payload\xff"
        )
        destination = self.root / "repacked"
        destination.mkdir()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "wheel",
                "pack",
                str(project),
                "-d",
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with WheelFile(destination / self.path.name) as wheel:
            self.assertEqual(
                wheel.read("fixture_package/__init__.py"), b"ANSWER = 42\n"
            )
            self.assertEqual(
                wheel.read("fixture_package/data.bin"), b"binary\0payload\xff"
            )

    def test_bad_filename_is_rejected(self):
        with self.assertRaisesRegex(WheelError, "Bad wheel filename"):
            WheelFile(self.root / "not-a-wheel.zip")


if __name__ == "__main__":
    import importlib.metadata
    import sys

    stream, distribution, version = sys.argv[1:]
    assert sys.version_info[:2] == tuple(map(int, stream.split(".")))
    assert importlib.metadata.version(distribution) == version
    unittest.main(argv=[sys.argv[0]], verbosity=2)
