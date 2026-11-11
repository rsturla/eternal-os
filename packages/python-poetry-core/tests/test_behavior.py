import contextlib
import os
import configparser
from email.parser import BytesParser
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

from installer import install
from installer.destinations import SchemeDictionaryDestination
from installer.sources import WheelFile
import poetry.core.masonry.api as backend


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.project = self.workspace / "project"
        shutil.copytree(Path(__file__).with_name("project"), self.project)
        self.wheels = self.workspace / "wheels"
        self.wheels.mkdir()
        self.dist_info = "fixture_poetry-1.2.3.dist-info"

    def build_wheel(self):
        with contextlib.chdir(self.project):
            name = backend.build_wheel(str(self.wheels))
        self.assertEqual(name, "fixture_poetry-1.2.3-py3-none-any.whl")
        return self.wheels / name

    def test_metadata_matches_declared_project(self):
        destination = self.workspace / "metadata"
        destination.mkdir()
        with contextlib.chdir(self.project):
            name = backend.prepare_metadata_for_build_wheel(str(destination))
        self.assertEqual(name, self.dist_info)
        metadata = BytesParser().parsebytes(
            (destination / name / "METADATA").read_bytes()
        )
        self.assertEqual(metadata["Name"], "fixture-poetry")
        self.assertEqual(metadata["Version"], "1.2.3")
        self.assertEqual(metadata["Requires-Python"], ">=3.11")
        entries = configparser.ConfigParser()
        entries.read(destination / name / "entry_points.txt")
        self.assertEqual(
            entries["console_scripts"]["fixture-answer"], "fixture_poetry:main"
        )

    def test_wheel_payload_metadata_and_install(self):
        path = self.build_wheel()
        with zipfile.ZipFile(path) as wheel:
            self.assertEqual(
                wheel.read("fixture_poetry/resource.txt"), b"packaged resource\n"
            )
            self.assertIn(b"ANSWER = 42", wheel.read("fixture_poetry/__init__.py"))
            metadata = BytesParser().parsebytes(
                wheel.read(self.dist_info + "/METADATA")
            )
            self.assertEqual(metadata["Name"], "fixture-poetry")
            self.assertEqual(metadata["Version"], "1.2.3")
            self.assertIn(b"Tag: py3-none-any", wheel.read(self.dist_info + "/WHEEL"))
            self.assertIn(
                "fixture_poetry/resource.txt",
                wheel.read(self.dist_info + "/RECORD").decode(),
            )
        root = self.workspace / "installed"
        scheme = {
            key: str(root / key)
            for key in ["purelib", "platlib", "headers", "scripts", "data"]
        }
        destination = SchemeDictionaryDestination(
            scheme,
            interpreter=sys.executable,
            script_kind="posix",
            bytecode_optimization_levels=[],
        )
        with WheelFile.open(path) as wheel:
            install(
                wheel, destination, additional_metadata={"INSTALLER": b"eternal-test\n"}
            )
        installed = root / "purelib"
        self.assertEqual(
            (installed / "fixture_poetry/resource.txt").read_bytes(),
            b"packaged resource\n",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import fixture_poetry; print(fixture_poetry.ANSWER)",
                str(installed),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "42\n")
        script = root / "scripts/fixture-answer"
        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))
        self.assertEqual(script.read_text().splitlines()[0], "#!" + sys.executable)
        result = subprocess.run(
            [str(script)],
            env={**os.environ, "PYTHONPATH": str(installed)},
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "42\n")
        self.assertEqual(
            (installed / self.dist_info / "INSTALLER").read_bytes(), b"eternal-test\n"
        )

    def test_sdist_contains_source_and_build_configuration(self):
        destination = self.workspace / "sdists"
        destination.mkdir()
        with contextlib.chdir(self.project):
            name = backend.build_sdist(str(destination))
        with tarfile.open(destination / name) as archive:
            names = archive.getnames()
            self.assertTrue(any(name.endswith("/pyproject.toml") for name in names))
            self.assertTrue(
                any(name.endswith("/src/fixture_poetry/__init__.py") for name in names)
            )
            self.assertTrue(
                any(name.endswith("/src/fixture_poetry/resource.txt") for name in names)
            )
            metadata = next(
                item for item in archive.getmembers() if item.name.endswith("/PKG-INFO")
            )
            info = BytesParser().parsebytes(archive.extractfile(metadata).read())
            self.assertEqual(info["Name"], "fixture-poetry")
            self.assertEqual(info["Version"], "1.2.3")

    def test_editable_wheel_tracks_source_changes(self):
        destination = self.workspace / "editable"
        destination.mkdir()
        with contextlib.chdir(self.project):
            name = backend.build_editable(str(destination))
        self.assertEqual(name, "fixture_poetry-1.2.3-py3-none-any.whl")
        installed = self.workspace / "editable-install"
        with zipfile.ZipFile(destination / name) as wheel:
            paths = [entry for entry in wheel.namelist() if entry.endswith(".pth")]
            self.assertTrue(paths)
            self.assertTrue(
                any(
                    str(self.project / "src") in wheel.read(path).decode()
                    for path in paths
                )
            )
            wheel.extractall(installed)
        (self.project / "src/fixture_poetry/__init__.py").write_text("ANSWER = 43\n")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import site, sys; site.addsitedir(sys.argv[1]); import fixture_poetry; print(fixture_poetry.ANSWER)",
                str(installed),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "43\n")

    def test_invalid_project_metadata_is_rejected(self):
        (self.project / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = ["invalid"]\n'
        )
        with contextlib.chdir(self.project), self.assertRaises(RuntimeError):
            backend.prepare_metadata_for_build_wheel(
                str(self.workspace / "invalid-metadata")
            )


if __name__ == "__main__":
    import importlib.metadata
    import sys

    stream, distribution, version = sys.argv[1:]
    assert sys.version_info[:2] == tuple(map(int, stream.split(".")))
    assert importlib.metadata.version(distribution) == version
    unittest.main(argv=[sys.argv[0]], verbosity=2)
