import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml


spec = importlib.util.spec_from_file_location(
    "python_bootstrap", Path(__file__).resolve().parents[1] / "scripts/build-python.py"
)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def plan(output, *, packages=(), needs=(), requires=(), provides=()):
    return {"cells": [{
        "packages": list(packages),
        "pipeline": [{"needs": list(needs)}],
        "outputs": [{"name": output, "requires": list(requires), "provides": list(provides)}],
    }]}


class PythonBootstrap(unittest.TestCase):
    def test_discovers_new_interpreter_without_version_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in {
                "python-3.15": {},
                "python-3.14": {},
                "python-demo": {"matrix": {"axes": {"python": []}}},
                "python-unrelated": {},
            }.items():
                path = root / "packages" / name / "package.yaml"
                path.parent.mkdir(parents=True)
                path.write_text(yaml.safe_dump(data))
            self.assertEqual(
                [path.parent.name for path in bootstrap.bootstrap_recipes(root)],
                ["python-3.14", "python-3.15", "python-demo"],
            )

    def test_new_stream_builds_runtime_and_module_dependencies_first(self):
        plans = {
            "python-3.15": plan("python-3.15"),
            "python-packaging": plan("python-3.15-packaging", packages=["python-3.15"]),
            "python-build": plan("python-3.14-build"),
            "python-demo": plan(
                "python-3.15-demo", packages=["python-3.15"],
                needs=["python-3.14-build"], requires=["python-3.15-packaging >= 1"],
            ),
        }
        order = bootstrap.dependency_order(plans, "python-demo")
        self.assertLess(order.index("python-3.15"), order.index("python-packaging"))
        self.assertLess(order.index("python-build"), order.index("python-demo"))
        self.assertLess(order.index("python-packaging"), order.index("python-demo"))

    def test_fedora_seed_does_not_resolve_to_an_eternal_module(self):
        plans = {
            "python-build": plan("python-3.14-build"),
            "python-demo": plan("python-3.15-demo", needs=["python3-build"]),
        }
        self.assertEqual(bootstrap.dependency_order(plans, "python-demo"), ["python-demo"])

    def test_dependency_cycle_fails_before_building(self):
        plans = {
            "python-a": plan("python-3.15-a", needs=["python-3.15-b"]),
            "python-b": plan("python-3.15-b", needs=["python-3.15-a"]),
        }
        with self.assertRaisesRegex(SystemExit, "dependency cycle"):
            bootstrap.dependency_order(plans, "python-a")

    def test_local_bootstrap_cache_tracks_preceding_dependencies(self):
        order = ["python", "backend", "module"]
        first = bootstrap.bootstrap_hashes(order, {"python": "a", "backend": "b", "module": "c"})
        changed = bootstrap.bootstrap_hashes(order, {"python": "a", "backend": "new", "module": "c"})
        self.assertEqual(first["python"], changed["python"])
        self.assertNotEqual(first["backend"], changed["backend"])
        self.assertNotEqual(first["module"], changed["module"])


if __name__ == "__main__":
    unittest.main()
