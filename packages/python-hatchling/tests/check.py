import importlib.metadata as metadata
import configparser
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
import shutil
import subprocess
import tarfile
import zipfile

source = Path("project").resolve()
shutil.copytree(fixtures / "project", source)
os.chdir(source)
dist = Path("dist").resolve()
dist.mkdir()
from hatchling import build as backend

wheel = dist / backend.build_wheel(str(dist))
with zipfile.ZipFile(wheel) as archive:
    assert b"ANSWER = 42" in archive.read("eternal_fixture.py")
    assert (
        "Version: 1.2.3"
        in archive.read("eternal_fixture-1.2.3.dist-info/METADATA").decode()
    )
    assert "eternal_fixture-1.2.3.dist-info/RECORD" in archive.namelist()
    entry_points = configparser.ConfigParser()
    entry_points.read_string(
        archive.read("eternal_fixture-1.2.3.dist-info/entry_points.txt").decode()
    )
    assert dict(entry_points["console_scripts"]) == {
        "eternal-fixture": "eternal_fixture:main"
    }, dict(entry_points["console_scripts"])
subprocess.run(
    [
        sys.executable,
        "-I",
        "-c",
        "import sys;sys.path.insert(0,sys.argv[1]);import eternal_fixture;assert eternal_fixture.ANSWER==42",
        str(wheel),
    ],
    check=True,
)
sdist = dist / backend.build_sdist(str(dist))
with tarfile.open(sdist) as archive:
    assert any(name.endswith("/pyproject.toml") for name in archive.getnames())
    assert any(name.endswith("/eternal_fixture.py") for name in archive.getnames())
editable = dist / backend.build_editable(str(dist))
with zipfile.ZipFile(editable) as archive:
    assert any(name.endswith(".pth") for name in archive.namelist())
    editable_site = source / "editable-site"
    archive.extractall(editable_site)
probe = "import site,sys;site.addsitedir(sys.argv[1]);import eternal_fixture;assert eternal_fixture.ANSWER==int(sys.argv[2])"
subprocess.run(
    [sys.executable, "-I", "-c", probe, str(editable_site), "42"], check=True
)
Path("eternal_fixture.py").write_text("ANSWER = 314159\n")
subprocess.run(
    [sys.executable, "-I", "-c", probe, str(editable_site), "314159"], check=True
)
config = Path("pyproject.toml")
config.write_text(config.read_text().replace('version = "1.2.3"\n', ""))
Path("bad-dist").mkdir()
failed = subprocess.run(
    [
        sys.executable,
        "-I",
        "-c",
        "from hatchling import build as backend; backend.build_wheel('bad-dist')",
    ],
    capture_output=True,
    text=True,
)
assert failed.returncode and "version" in (failed.stdout + failed.stderr).lower(), (
    failed.stdout + failed.stderr
)
