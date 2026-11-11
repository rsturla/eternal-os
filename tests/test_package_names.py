import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml


spec = importlib.util.spec_from_file_location(
    "package_names", Path(__file__).resolve().parents[1] / "scripts/check-package-names.py"
)
names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(names)


class PackageNames(unittest.TestCase):
    def fixture(self, output="python-${matrix.python.version}-demo", versions=("3.13", "3.14"), streams=("3.13", "3.14")):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for stream in streams:
            path = root / "packages" / f"python-{stream}" / "package.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(yaml.safe_dump({
                "package": {"name": f"python-{stream}"},
                "outputs": [{"name": f"python-{stream}-default", "dependencies": {"provides": [
                    "python3 = ${package.version}-${package.release}"
                ], "conflicts": [f"python-{other}-default" for other in streams if other != stream]}}],
            }))
        recipe = {
            "package": {"name": "python-demo"},
            "matrix": {"axes": {"python": [{"version": stream} for stream in versions]}},
            "outputs": [{"name": output}],
        }
        path = root / "packages/python-demo/package.yaml"
        path.parent.mkdir()
        path.write_text(yaml.safe_dump(recipe))
        return root

    def assert_problem(self, root, source, message):
        path = root / "packages" / source / "package.yaml"
        self.assertEqual(names.check(root), [f"{path}: {message}"])

    def test_versioned_modules_and_user_selectors_are_valid(self):
        self.assertEqual(names.check(self.fixture()), [])

    def test_new_stream_has_no_distro_default(self):
        versions = ("3.13", "3.14", "3.15")
        self.assertEqual(names.check(self.fixture(versions=versions, streams=versions)), [])

    def test_every_selector_provides_its_full_version(self):
        root = self.fixture()
        path = root / "packages/python-3.13/package.yaml"
        data = yaml.safe_load(path.read_text())
        data["outputs"][0]["dependencies"]["provides"] = ["python3 = 0"]
        path.write_text(yaml.safe_dump(data))
        self.assert_problem(
            root, "python-3.13",
            "default command output must provide python3 = ${package.version}-${package.release}",
        )

    def test_unversioned_module_alias_is_rejected(self):
        root = self.fixture()
        path = root / "packages/python-demo/package.yaml"
        data = yaml.safe_load(path.read_text())
        data["outputs"][0]["dependencies"] = {"provides": ["python-demo = 1-1"]}
        path.write_text(yaml.safe_dump(data))
        self.assert_problem(
            root, "python-demo",
            "Python modules must not provide the unversioned python-demo alias",
        )

    def test_fedora_style_module_identity_is_rejected(self):
        root = self.fixture(output="python${matrix.python.version}-demo")
        self.assert_problem(
            root, "python-demo", "main output must be python-${matrix.python.version}-demo",
        )

    def test_missing_supported_stream_is_rejected(self):
        root = self.fixture(versions=("3.14",))
        self.assert_problem(
            root, "python-demo", "Python matrix must cover supported streams ['3.13', '3.14']",
        )


if __name__ == "__main__":
    unittest.main()
