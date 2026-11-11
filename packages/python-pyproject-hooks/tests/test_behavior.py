from email.parser import BytesParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

from pyproject_hooks import BackendUnavailable, BuildBackendHookCaller, HookMissing


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()
        self.project = self.workspace / "project"
        shutil.copytree(Path(__file__).with_name("project"), self.project)
        self.output = self.workspace / "output"
        self.output.mkdir()

    def caller(self, backend="backend"):
        return BuildBackendHookCaller(
            str(self.project),
            backend,
            backend_path=["."],
            python_executable=sys.executable,
        )

    def test_requirement_settings_are_transported(self):
        caller = self.caller()
        self.assertEqual(caller.get_requires_for_build_wheel(), ["fixture-default>=1"])
        self.assertEqual(
            caller.get_requires_for_build_wheel({"marker": "custom"}),
            ["fixture-custom>=1"],
        )

    def test_build_wheel_uses_the_selected_interpreter(self):
        caller = self.caller()
        name = caller.build_wheel(str(self.output), {"marker": "wheel"})
        self.assertEqual(name, "fixture_hooks-1.2.3-py3-none-any.whl")
        with zipfile.ZipFile(self.output / name) as wheel:
            self.assertEqual(wheel.read("fixture_hooks.py"), b"ANSWER = 42\n")
            execution = json.loads(wheel.read("execution.json"))
            self.assertEqual(
                Path(execution["executable"]).resolve(), Path(sys.executable).resolve()
            )
            self.assertEqual(execution["version"], list(sys.version_info[:2]))
            self.assertEqual(execution["settings"], {"marker": "wheel"})

    def test_metadata_falls_back_to_wheel_hook(self):
        caller = self.caller()
        name = caller.prepare_metadata_for_build_wheel(str(self.output))
        self.assertEqual(name, "fixture_hooks-1.2.3.dist-info")
        metadata = BytesParser().parsebytes(
            (self.output / name / "METADATA").read_bytes()
        )
        self.assertEqual(metadata["Name"], "fixture-hooks")
        self.assertEqual(metadata["Version"], "1.2.3")
        with self.assertRaises(HookMissing):
            caller.prepare_metadata_for_build_wheel(
                str(self.output), _allow_fallback=False
            )

    def test_source_archive_hook(self):
        name = self.caller().build_sdist(str(self.output))
        self.assertEqual(name, "fixture_hooks-1.2.3.tar.gz")
        with tarfile.open(self.output / name) as archive:
            self.assertEqual(
                archive.extractfile("fixture_hooks-1.2.3/README").read(),
                b"offline fixture source\n",
            )

    def test_optional_and_missing_hooks(self):
        caller = self.caller("empty_backend")
        self.assertEqual(caller.get_requires_for_build_wheel(), [])
        self.assertEqual(caller.get_requires_for_build_sdist(), [])
        with self.assertRaises(HookMissing):
            caller.build_editable(str(self.output))

    def test_missing_backend_and_backend_error(self):
        with self.assertRaises(BackendUnavailable):
            self.caller("nonexistent_backend").get_requires_for_build_wheel()
        with self.assertRaises(subprocess.CalledProcessError):
            self.caller().build_wheel(str(self.output), {"fail": True})

    def test_backend_path_cannot_escape_source(self):
        with self.assertRaises(ValueError):
            BuildBackendHookCaller(
                str(self.project),
                "backend",
                backend_path=[".."],
                python_executable=sys.executable,
            )

    def test_custom_subprocess_runner(self):
        calls = []

        def runner(command, cwd=None, extra_environ=None):
            calls.append((command, cwd))
            subprocess.run(
                command,
                cwd=cwd,
                env={**os.environ, **(extra_environ or {})},
                check=True,
            )

        caller = self.caller()
        with caller.subprocess_runner(runner):
            self.assertEqual(
                caller.get_requires_for_build_wheel(), ["fixture-default>=1"]
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(Path(calls[0][0][0]).resolve(), Path(sys.executable).resolve())
        self.assertEqual(Path(calls[0][1]).resolve(), self.project)


if __name__ == "__main__":
    import importlib.metadata
    import sys

    stream, distribution, version = sys.argv[1:]
    assert sys.version_info[:2] == tuple(map(int, stream.split(".")))
    assert importlib.metadata.version(distribution) == version
    unittest.main(argv=[sys.argv[0]], verbosity=2)
