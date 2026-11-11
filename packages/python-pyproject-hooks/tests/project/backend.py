"""A local backend used to test hook transport without another build backend."""

import csv
import hashlib
import base64
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile


def get_requires_for_build_wheel(config_settings=None):
    marker = (config_settings or {}).get("marker", "default")
    return [f"fixture-{marker}>=1"]


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    settings = config_settings or {}
    if settings.get("fail"):
        raise RuntimeError("deliberate backend failure")
    name = "fixture_hooks-1.2.3-py3-none-any.whl"
    info = "fixture_hooks-1.2.3.dist-info"
    entries = {
        "fixture_hooks.py": b"ANSWER = 42\n",
        "execution.json": json.dumps(
            {
                "executable": sys.executable,
                "version": list(sys.version_info[:2]),
                "settings": settings,
            }
        ).encode(),
        info
        + "/METADATA": b"Metadata-Version: 2.1\nName: fixture-hooks\nVersion: 1.2.3\n",
        info
        + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = io.StringIO()
    writer = csv.writer(record)
    for filename, contents in entries.items():
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(contents).digest())
            .rstrip(b"=")
            .decode()
        )
        writer.writerow([filename, "sha256=" + digest, len(contents)])
    writer.writerow([info + "/RECORD", "", ""])
    entries[info + "/RECORD"] = record.getvalue().encode()
    with zipfile.ZipFile(Path(wheel_directory) / name, "w") as wheel:
        for filename, contents in entries.items():
            wheel.writestr(filename, contents)
    return name


def build_sdist(sdist_directory, config_settings=None):
    name = "fixture_hooks-1.2.3.tar.gz"
    content = b"offline fixture source\n"
    with tarfile.open(Path(sdist_directory) / name, "w:gz") as archive:
        info = tarfile.TarInfo("fixture_hooks-1.2.3/README")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return name
