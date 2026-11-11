import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
from build import ProjectBuilder
import shutil
import subprocess
import tarfile
import zipfile

source = Path("project").resolve()
shutil.copytree(fixtures / "project", source)
builder = ProjectBuilder(str(source), python_executable=sys.executable)
assert builder.build_system_requires == {"flit_core"}
assert not builder.check_dependencies("wheel")
metadata_path = builder.prepare("wheel", "metadata")
assert metadata_path and (Path(metadata_path) / "METADATA").is_file()
wheel = Path(builder.build("wheel", "dist"))
with zipfile.ZipFile(wheel) as archive:
    assert archive.read("eternal_fixture.py").find(b"ANSWER = 42") >= 0
    assert (
        "Version: 1.2.3"
        in archive.read("eternal_fixture-1.2.3.dist-info/METADATA").decode()
    )
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
sdist = Path(builder.build("sdist", "dist"))
with tarfile.open(sdist) as archive:
    assert any(name.endswith("/pyproject.toml") for name in archive.getnames())
# Exercise the installed CLI without creating or populating an isolated env.
subprocess.run(
    [
        sys.executable,
        "-I",
        "-m",
        "build",
        "--no-isolation",
        "--wheel",
        "--outdir",
        "cli-dist",
        str(source),
    ],
    check=True,
)
assert list(Path("cli-dist").glob("*.whl"))
(source / "pyproject.toml").write_text(
    "[build-system]\nrequires = []\nbuild-backend = 'eternal_missing_backend'\n"
)
failed = subprocess.run(
    [sys.executable, "-I", "-m", "build", "--no-isolation", "--wheel", str(source)],
    capture_output=True,
    text=True,
)
assert failed.returncode and "eternal_missing_backend" in failed.stdout + failed.stderr
