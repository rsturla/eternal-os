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
    def fixture(self, output="python-${matrix.python.version}-demo", versions=("3.13", "3.14"), streams=("3.13", "3.14"), default="3.14"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "rpmx-defaults.yaml").write_text(yaml.safe_dump({"metadata": {"python": {"default-stream": default}}}))
        for stream in streams:
            path = root / "packages" / f"python-{stream}" / "package.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(yaml.safe_dump({
                "package": {"name": f"python-{stream}"},
                "outputs": [{"name": f"python-{stream}-default", "dependencies": {"provides": [
                    "python3 = ${package.version}-${package.release}" if stream == default else "python3 = 0"
                ]}}],
            }))
        recipe = {
            "package": {"name": "python-demo"},
            "matrix": {"axes": {"python": [
                {"version": stream, "capability": "python" if stream == default else "python-" + stream}
                for stream in versions
            ]}},
            "outputs": [{"name": output, "dependencies": {"provides": [
                "${matrix.python.capability}-demo = 1-1"
            ]}}],
        }
        path = root / "packages/python-demo/package.yaml"
        path.parent.mkdir()
        path.write_text(yaml.safe_dump(recipe))
        return root

    def test_interpreter_namespace_and_default_capability_are_valid(self):
        self.assertEqual(names.check(self.fixture()), [])

    def test_new_stream_can_be_staged_without_promoting_the_default(self):
        versions = ("3.13", "3.14", "3.15")
        self.assertEqual(names.check(self.fixture(versions=versions, streams=versions)), [])

    def test_default_promotion_requires_matching_module_capabilities(self):
        root = self.fixture()
        (root / "rpmx-defaults.yaml").write_text(yaml.safe_dump({"metadata": {"python": {"default-stream": "3.13"}}}))
        self.assertTrue(names.check(root))

    def test_new_interpreter_cannot_take_the_default_command_capability(self):
        versions = ("3.13", "3.14", "3.15")
        root = self.fixture(versions=versions, streams=versions)
        path = root / "packages/python-3.15/package.yaml"
        data = yaml.safe_load(path.read_text())
        data["outputs"][0]["dependencies"]["provides"] = ["python3 = ${package.version}-${package.release}"]
        path.write_text(yaml.safe_dump(data))
        self.assertTrue(names.check(root))

    def test_unsupported_default_is_rejected(self):
        self.assertTrue(names.check(self.fixture(default="3.15")))

    def test_fedora_style_module_identity_is_rejected(self):
        self.assertTrue(names.check(self.fixture(output="python${matrix.python.version}-demo")))

    def test_missing_supported_stream_is_rejected(self):
        self.assertTrue(names.check(self.fixture(versions=("3.14",))))


if __name__ == "__main__":
    unittest.main()
