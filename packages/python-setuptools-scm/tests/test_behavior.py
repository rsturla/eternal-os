import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from setuptools_scm import get_version


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("SETUPTOOLS_SCM_", "VCS_VERSIONING_", "GIT_"))
        }
        self.environment = patch.dict(os.environ, environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def infer(self, **overrides):
        configuration = dict(
            root=str(self.root),
            fallback_root=str(self.root),
            local_scheme="no-local-version",
        )
        configuration.update(overrides)
        return get_version(dist_name="fixture-package", **configuration)

    def git(self, *arguments):
        return subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Eternal fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                *arguments,
            ],
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            },
        )

    def tagged_repository(self):
        self.git("init", "--quiet")
        (self.root / "payload").write_text("first\n")
        self.git("add", "payload")
        self.git("commit", "--quiet", "-m", "initial fixture")
        self.git("tag", "v1.2.3")

    def test_cli_reads_local_tag(self):
        self.tagged_repository()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "setuptools_scm",
                "--root",
                str(self.root),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout, "1.2.3\n")

    def test_tag_version_is_exact(self):
        self.tagged_repository()
        self.assertEqual(self.infer(), "1.2.3")

    def test_commit_distance_advances_development_version(self):
        self.tagged_repository()
        (self.root / "payload").write_text("second\n")
        self.git("commit", "--quiet", "-am", "second fixture")
        self.assertEqual(self.infer(), "1.2.4.dev1")

    def test_dirty_tree_is_not_a_release(self):
        self.tagged_repository()
        (self.root / "payload").write_text("uncommitted\n")
        self.assertEqual(self.infer(), "1.2.4.dev0")

    def test_explicit_fallback_without_vcs(self):
        self.assertEqual(self.infer(fallback_version="4.5.6"), "4.5.6")

    def test_missing_vcs_and_fallback_is_an_error(self):
        with self.assertRaises(LookupError):
            self.infer()

    def test_distribution_specific_override(self):
        with patch.dict(
            os.environ, {"SETUPTOOLS_SCM_PRETEND_VERSION_FOR_FIXTURE_PACKAGE": "9.8.7"}
        ):
            self.assertEqual(self.infer(), "9.8.7")


if __name__ == "__main__":
    import importlib.metadata
    import sys

    stream, distribution, version = sys.argv[1:]
    assert sys.version_info[:2] == tuple(map(int, stream.split(".")))
    assert importlib.metadata.version(distribution) == version
    unittest.main(argv=[sys.argv[0]], verbosity=2)
