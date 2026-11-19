import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
import json
import runpy
import subprocess
from pip._vendor import certifi, msgpack, urllib3

assert urllib3.__version__ == "2.8.0"
assert msgpack.version == (1, 2, 3)
assert certifi.__version__ == "2026.10.23"
assert msgpack.unpackb(msgpack.packb({"answer": 42})) == {"answer": 42}
make_wheel = runpy.run_path(str(fixtures / "wheel_fixture.py"))["wheel"]
archive = make_wheel("wheels")
base_env = {
    **os.environ,
    "PIP_CONFIG_FILE": os.devnull,
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INDEX": "1",
    "PIP_NO_CACHE_DIR": "1",
}


def pip(*args, success=True):
    result = subprocess.run(
        [sys.executable, "-I", "-m", "pip", *args],
        env=base_env,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


site = Path("site").resolve()
pip(
    "install",
    "--no-index",
    "--no-deps",
    "--no-compile",
    "--target",
    str(site),
    str(archive),
)
subprocess.run(
    [
        sys.executable,
        "-I",
        "-c",
        "import sys;sys.path.insert(0,sys.argv[1]);import eternal_fixture;assert eternal_fixture.ANSWER==42",
        str(site),
    ],
    check=True,
)
assert (site / "eternal_fixture-1.0.dist-info/INSTALLER").read_text().strip() == "pip"
assert json.loads((site / "eternal_fixture-1.0.dist-info/direct_url.json").read_text())[
    "url"
].endswith(archive.name)
pip("wheel", "--no-index", "--no-deps", "--wheel-dir", "copied", str(archive))
assert (Path("copied") / archive.name).read_bytes() == archive.read_bytes()
pip("download", "--no-index", "--no-deps", "--dest", "downloaded", str(archive))
assert (Path("downloaded") / archive.name).read_bytes() == archive.read_bytes()
needed = make_wheel("requires", version="2.0", requirement="eternal-fixture-missing>=1")
failure = pip(
    "install", "--no-index", "--target", "unsatisfied", str(needed), success=False
)
assert "eternal-fixture-missing" in failure.stdout + failure.stderr
missing = pip(
    "install",
    "--no-index",
    "--target",
    "missing",
    "eternal-fixture-deliberately-absent",
    success=False,
)
assert "eternal-fixture-deliberately-absent" in missing.stdout + missing.stderr
assert any(
    item["name"] == "eternal-fixture" and item["version"] == "1.0"
    for item in json.loads(pip("list", "--path", str(site), "--format=json").stdout)
)

# Create a local environment without ensurepip or downloads. The packaged pip
# controls its versioned interpreter, including real uninstall transactions.
import venv

venv_root = Path("venv").resolve()
venv.EnvBuilder(with_pip=False).create(venv_root)
interpreter = venv_root / "bin" / ("python" + sys.argv[1])
pip("--python", str(interpreter), "install", "--no-index", "--no-deps", str(archive))
subprocess.run(
    [
        str(interpreter),
        "-I",
        "-c",
        "import eternal_fixture;assert eternal_fixture.ANSWER==42",
    ],
    check=True,
)
launched = subprocess.run(
    [str(venv_root / "bin/eternal-fixture")], capture_output=True, text=True, check=True
)
assert launched.stdout == "fixture-cli-ok\n"
pip("--python", str(interpreter), "check")
shown = pip("--python", str(interpreter), "show", "--files", "eternal-fixture").stdout
assert "Version: 1.0" in shown and "eternal_fixture/__init__.py" in shown
pip("--python", str(interpreter), "uninstall", "-y", "eternal-fixture")
subprocess.run(
    [
        str(interpreter),
        "-I",
        "-c",
        "import importlib.util;assert importlib.util.find_spec('eternal_fixture') is None",
    ],
    check=True,
)
assert not (venv_root / "bin/eternal-fixture").exists()
