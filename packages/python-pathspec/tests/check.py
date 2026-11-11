import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
from pathspec import GitIgnoreSpec, PathSpec

rules = [
    "*.pyc",
    "__pycache__/",
    "build/",
    "!build/keep.txt",
    "/root-only.txt",
    "secret/**",
]
spec = GitIgnoreSpec.from_lines(rules)
for path in [
    "module.pyc",
    "nested/module.pyc",
    "__pycache__/cache",
    "build/result",
    "root-only.txt",
    "secret/nested/key",
]:
    assert spec.match_file(path), path
for path in ["module.py", "build/keep.txt", "nested/root-only.txt", "public/key"]:
    assert not spec.match_file(path), path
assert set(spec.match_files(["a.pyc", "a.py", "build/result"])) == {
    "a.pyc",
    "build/result",
}
files = Path("tree")
(files / "sub").mkdir(parents=True)
(files / "keep.py").write_text("pass\n")
(files / "sub" / "drop.pyc").write_bytes(b"cache")
matched = set(PathSpec.from_lines("gitwildmatch", ["*.pyc"]).match_tree_files(files))
assert matched == {"sub/drop.pyc"}, matched
escaped = GitIgnoreSpec.from_lines(
    [r"\#literal", r"\!literal", "[ab].txt", "**/generated/*"]
)
for path in ["#literal", "!literal", "a.txt", "sub/generated/object"]:
    assert escaped.match_file(path), path
assert not escaped.match_file("c.txt")
