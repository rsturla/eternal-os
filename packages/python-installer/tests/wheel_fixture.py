import base64
import csv
import hashlib
import io
import zipfile
from pathlib import Path


def wheel(directory, version="1.0", requirement=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    dist = f"eternal_fixture-{version}.dist-info"
    package = {
        "eternal_fixture/__init__.py": b"ANSWER = 42\n",
        "eternal_fixture/cli.py": b"def main():\n    print('fixture-cli-ok')\n",
        f"{dist}/METADATA": (
            "Metadata-Version: 2.1\nName: eternal-fixture\n"
            f"Version: {version}\n"
            + (f"Requires-Dist: {requirement}\n" if requirement else "")
        ).encode(),
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: eternal-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{dist}/entry_points.txt": b"[console_scripts]\neternal-fixture = eternal_fixture.cli:main\n",
    }
    records = io.StringIO(newline="")
    writer = csv.writer(records, lineterminator="\n")
    for name, data in package.items():
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            .rstrip(b"=")
            .decode()
        )
        writer.writerow([name, f"sha256={digest}", len(data)])
    writer.writerow([f"{dist}/RECORD", "", ""])
    package[f"{dist}/RECORD"] = records.getvalue().encode()
    path = directory / f"eternal_fixture-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in package.items():
            archive.writestr(name, data)
    return path
