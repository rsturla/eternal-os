import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
from editables import EditableProject, EditableException
import site
import subprocess

source = Path("source").resolve()
(source / "src" / "mapped_package").mkdir(parents=True)
(source / "src" / "mapped_package" / "__init__.py").write_text("VALUE = 42\n")
(source / "src" / "mapped_package" / "child.py").write_text("VALUE = 'child'\n")
project = EditableProject("eternal-fixture", source)
project.map("mapped_package", "src/mapped_package")
site_dir = Path("installed").resolve()
site_dir.mkdir()
for name, content in project.files():
    target = site_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
assert "editables" in project.dependencies()
probe = "import site,sys; site.addsitedir(sys.argv[1]); import mapped_package, mapped_package.child; assert mapped_package.VALUE == int(sys.argv[2]); assert mapped_package.child.VALUE == 'child'"
subprocess.run([sys.executable, "-I", "-c", probe, str(site_dir), "42"], check=True)
# A fresh interpreter must see changed source, without rebuilding the mapping.
(source / "src" / "mapped_package" / "__init__.py").write_text("VALUE = 314159\n")
subprocess.run([sys.executable, "-I", "-c", probe, str(site_dir), "314159"], check=True)
path_project = EditableProject("path-fixture", source)
path_project.add_to_path("src")
assert any(str(source / "src") in content for _, content in path_project.files())
try:
    project.map("invalid.dotted", "src/mapped_package")
except EditableException:
    pass
else:
    raise AssertionError("dotted module mapping accepted")
