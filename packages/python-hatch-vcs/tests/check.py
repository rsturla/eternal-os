import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
from hatch_vcs.version_source import VCSVersionSource
from hatchling import build
from packaging.version import Version
import shutil
import subprocess
import zipfile

source = Path("project").resolve()
shutil.copytree(fixtures / "project", source)
git_env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
for key in list(git_env):
    if key.startswith("SETUPTOOLS_SCM_PRETEND_VERSION"):
        del git_env[key]


def git(*args):
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Eternal tests",
            "-c",
            "user.email=tests@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        env=git_env,
        check=True,
        capture_output=True,
    )


git("init", "-b", "main")
git("add", ".")
git("commit", "-m", "initial fixture")
git("tag", "v1.2.3")
version_source = VCSVersionSource(str(source), {})
assert version_source.get_version_data()["version"] == "1.2.3"
os.chdir(source)
Path("dist").mkdir()
wheel = Path("dist") / build.build_wheel("dist")
with zipfile.ZipFile(wheel) as archive:
    assert b"Version: 1.2.3" in archive.read("eternal_fixture-1.2.3.dist-info/METADATA")
    generated = archive.read("eternal_fixture/_version.py").decode()
    namespace = {}
    exec(compile(generated, "_version.py", "exec"), namespace)
    assert namespace["__version__"] == "1.2.3"
(source / "eternal_fixture/__init__.py").write_text("ANSWER = 43\n")
git("add", "eternal_fixture/__init__.py")
git("commit", "-m", "change fixture")
development = Version(version_source.get_version_data()["version"])
assert development.is_devrelease and development > Version("1.2.3")
missing = source.parent / "no-repository"
missing.mkdir()
try:
    VCSVersionSource(str(missing), {}).get_version_data()
except LookupError:
    pass
else:
    raise AssertionError("missing version-control metadata accepted")
