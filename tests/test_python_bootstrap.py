import importlib.util
import io
from contextlib import redirect_stdout
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
    def test_bootstrap_requires_a_concrete_architecture_before_planning(self):
        with patch.object(sys, "argv", ["build-python.py", "python-demo", "--output", "out", "--arch", "all"]), \
                patch.object(bootstrap.subprocess, "check_output") as capture, \
                patch.object(sys, "stderr", new_callable=io.StringIO) as diagnostics:
            with self.assertRaises(SystemExit) as failure:
                bootstrap.main()
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("requires one concrete --arch", diagnostics.getvalue())
        capture.assert_not_called()

    def test_optional_and_disabled_tests_conflict_before_planning(self):
        arguments = ["build-python.py", "python-demo", "--output", "out",
                     "--include-optional-tests", "--no-tests"]
        with patch.object(sys, "argv", arguments), \
                patch.object(bootstrap.subprocess, "check_output") as capture, \
                patch.object(sys, "stderr", new_callable=io.StringIO) as diagnostics:
            with self.assertRaises(SystemExit) as failure:
                bootstrap.main()
        self.assertEqual(failure.exception.code, 2)
        self.assertIn("cannot be combined with --no-tests", diagnostics.getvalue())
        capture.assert_not_called()

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

    def test_optional_test_tools_are_built_only_when_requested(self):
        plans = {"python-demo": plan("python-3.15-demo"),
                 "source-tool": plan("python-3.15-source-tool"),
                 "installed-tool": plan("python-3.15-installed-tool")}
        cell = plans["python-demo"]["cells"][0]
        cell["build_tests"] = [{"optional": True, "packages": ["python-3.15-source-tool"]}]
        cell["tests"] = [{"optional": True, "pipeline": [{"needs": ["python-3.15-installed-tool"]}]}]
        self.assertEqual(bootstrap.dependency_order(plans, "python-demo"), ["python-demo"])
        order = bootstrap.dependency_order(plans, "python-demo", include_optional_tests=True)
        self.assertEqual(set(order), set(plans))
        self.assertEqual(order[-1], "python-demo")
        self.assertEqual(bootstrap.dependency_order(plans, "python-demo", include_tests=False,
                                                  include_optional_tests=True), ["python-demo"])

    def test_unpublished_test_tools_are_built_before_the_consumer(self):
        consumer = plan("python-3.15-demo")
        consumer["cells"][0]["tests"] = [{
            "packages": ["python-3.15-installer"],
            "pipeline": [{"needs": ["python-3.15-wheel"]}],
        }]
        consumer["cells"][0]["build_tests"] = [{
            "packages": ["python-3.15-source-tool"], "pipeline": [],
        }]
        plans = {
            "python-demo": consumer,
            "python-source-tool": plan("python-3.15-source-tool"),
            "python-installer": plan("python-3.15-installer"),
            "python-wheel": plan("python-3.15-wheel"),
        }
        order = bootstrap.dependency_order(plans, "python-demo")
        self.assertLess(order.index("python-source-tool"), order.index("python-demo"))
        self.assertLess(order.index("python-installer"), order.index("python-demo"))
        self.assertLess(order.index("python-wheel"), order.index("python-demo"))
        self.assertEqual(
            bootstrap.dependency_order(plans, "python-demo", include_tests=False),
            ["python-demo"],
        )

    def test_main_prepares_test_dependencies_and_relocates_both_profiles(self):
        for no_tests, include_optional_tests in ((False, False), (True, False), (False, True)):
            with self.subTest(no_tests=no_tests, optional=include_optional_tests), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "scripts").mkdir()
                (root / "profiles/repo").mkdir(parents=True)
                (root / "profiles/key file.asc").write_text("different key")
                (root / "profiles/key%20file.asc").write_text("literal public key")
                policy = {"repositories": [{
                    "id": "published", "baseurl": "file://repo",
                    "gpgkey": "file://key%20file.asc",
                }]}
                toolchain = root / "profiles/toolchain/repodata/repomd.xml"
                toolchain.parent.mkdir(parents=True)
                toolchain.write_text("shared seed metadata")
                build_policy = {"repositories": [
                    {**policy["repositories"][0], "exclude": ["build-only-exclusion"]},
                    {"id": "eternal-toolchain", "baseurl": "file://toolchain"},
                ]}
                runtime_policy = {"repositories": [
                    {**policy["repositories"][0], "exclude": ["runtime-only-exclusion"]},
                ]}
                (root / "profiles/bootstrap-python.profile.yaml").write_text(yaml.safe_dump(build_policy))
                (root / "profiles/runtime.yaml").write_text(yaml.safe_dump(runtime_policy))
                plans = {
                    "python-demo": plan("python-3.15-demo"),
                    "python-tool": plan("python-3.15-tool"),
                }
                plans["python-demo"]["cells"][0]["tests"] = [{
                    "packages": ["python-3.15-tool"], "pipeline": [],
                }]
                for name in plans:
                    recipe = root / "packages" / name / "package.yaml"
                    recipe.parent.mkdir(parents=True)
                    recipe.write_text("matrix:\n  axes:\n    python: []\n")
                builds = []
                hashes = {name: "hash-" + name for name in plans}

                def capture(command, **kwargs):
                    if command[1] == "plan":
                        return json.dumps({"plan": plans[Path(command[2]).parent.name]})
                    return "".join(name + " " + hashes[name] + "\n" for name in command[1:])

                def run(command, **kwargs):
                    if command[1].endswith("accept-rpms.py"):
                        self.assertEqual("--include-optional-tests" in command, include_optional_tests)
                        runtime = yaml.safe_load(Path(command[command.index("--test-profile") + 1]).read_text())
                        published = next(r for r in runtime["repositories"] if r["id"] == "published")
                        self.assertEqual(published["baseurl"], f"file://{root / 'profiles/repo'}")
                        self.assertIn("runtime-only-exclusion", published["exclude"])
                        self.assertNotIn("build-only-exclusion", published["exclude"])
                        self.assertFalse(any(r["id"] == "eternal-toolchain" for r in runtime["repositories"]))
                        if Path(command[2]).parent.name == "python-demo":
                            self.assertEqual(runtime["repositories"][0]["id"], "python-local")
                            self.assertIn("python-3.15-tool", published["exclude"])
                        return
                    if command[1] != "build":
                        return
                    name = Path(command[2]).parent.name
                    self.assertEqual("--include-optional-tests" in command, include_optional_tests)
                    generated = yaml.safe_load(Path(command[command.index("--profile") + 1]).read_text())
                    private_seed = next(r for r in generated["repositories"] if r["id"] == "eternal-toolchain")
                    private_metadata = Path(private_seed["baseurl"][7:]) / "repodata/repomd.xml"
                    self.assertNotEqual(private_metadata.resolve(), toolchain.resolve())
                    self.assertEqual(private_metadata.read_text(), "shared seed metadata")
                    self.assertEqual(toolchain.read_text(), "shared seed metadata")
                    policies = [generated]
                    if no_tests:
                        self.assertNotIn("--test-profile", command)
                        self.assertNotIn("--junit", command)
                        self.assertIn("--no-tests", command)
                    else:
                        self.assertNotIn("--test-profile", command)
                    for settings in policies:
                        published = next(r for r in settings["repositories"] if r["id"] == "published")
                        self.assertEqual(published["baseurl"], f"file://{root / 'profiles/repo'}")
                        self.assertIn("build-only-exclusion", published["exclude"])
                        self.assertNotIn("runtime-only-exclusion", published["exclude"])
                        self.assertEqual(published["gpgkey"], f"file://{root / 'profiles/key%20file.asc'}")
                        self.assertEqual(Path(published["gpgkey"][7:]).read_text(), "literal public key")
                        if name == "python-demo" and not no_tests:
                            self.assertEqual(settings["repositories"][0]["id"], "python-local")
                            self.assertIn("python-3.15-tool", published["exclude"])
                    builds.append(name)
                    output = Path(command[command.index("--output") + 1]) / "x86_64"
                    if name == "python-demo":
                        self.assertFalse((output.parent / "run-report.json").exists())
                        self.assertFalse((output.parent / "acceptance/x86_64/results.json").exists())
                    output.mkdir(parents=True, exist_ok=True)
                    (output / (name + ".rpm")).write_text("fixture RPM")
                    (output.parent / "run-report.json").write_text(json.dumps({
                        "document": "rpmx-run-report", "version": 1, "outcome": "passed",
                        "build_tests_requested": not no_tests, "build_tests": [], "evidence": [],
                    }))

                args = ["build-python.py", "python-demo",
                        "--arch", "x86_64", "--output", str(root / "out"),
                        "--test-profile", str(root / "profiles/runtime.yaml")]
                previous = root / "out/acceptance/x86_64/results.json"
                previous.parent.mkdir(parents=True)
                previous.write_text('{"outcome": "passed"}')
                (root / "out/run-report.json").write_text('{"outcome": "passed"}')
                if no_tests:
                    args.append("--no-tests")
                if include_optional_tests:
                    args.append("--include-optional-tests")
                with patch.object(bootstrap, "__file__", str(root / "scripts/build-python.py")), \
                        patch.object(sys, "argv", args), \
                        patch.object(bootstrap.subprocess, "check_output", side_effect=capture), \
                        patch.object(bootstrap.subprocess, "run", side_effect=run):
                    bootstrap.main()
                    actual_builds = builds.copy()
                    with patch.object(sys, "argv", [*args, "--fingerprint"]), redirect_stdout(io.StringIO()) as first:
                        bootstrap.main()
                    if not no_tests:
                        other_policy = ([arg for arg in args if arg != "--include-optional-tests"]
                                        if include_optional_tests else [*args, "--include-optional-tests"])
                        with patch.object(sys, "argv", [*other_policy, "--fingerprint"]), redirect_stdout(io.StringIO()) as other:
                            bootstrap.main()
                        self.assertNotEqual(first.getvalue(), other.getvalue(),
                                            "optional selection must not reuse a mandatory-only cache")
                    hashes["python-tool"] = "changed-test-tool"
                    with patch.object(sys, "argv", [*args, "--fingerprint"]), redirect_stdout(io.StringIO()) as changed:
                        bootstrap.main()
                    self.assertEqual(builds, actual_builds, "fingerprints must not build packages")
                    if no_tests:
                        self.assertEqual(first.getvalue(), changed.getvalue())
                    else:
                        self.assertNotEqual(first.getvalue(), changed.getvalue())
                self.assertEqual(builds, ["python-demo"] if no_tests else ["python-tool", "python-demo"])

    def test_main_keeps_distinct_dependency_reports_on_failure_and_cache_hits(self):
        for failed_name in (None, "python-tool-a", "python-demo"):
            with self.subTest(failed_name=failed_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "scripts").mkdir()
                (root / "profiles").mkdir()
                for name in ("bootstrap-python.profile.yaml", "eternal.profile.yaml"):
                    (root / "profiles" / name).write_text("repositories: []\n")
                plans = {
                    "python-tool-a": plan("python-3.15-tool-a"),
                    "python-tool-b": plan("python-3.15-tool-b"),
                    "python-demo": plan("python-3.15-demo", packages=[
                        "python-3.15-tool-a", "python-3.15-tool-b",
                    ]),
                }
                recipes = [root / "packages" / name / "package.yaml" for name in plans]
                reports = root / "out/test-reports"
                calls = []

                def capture(command, **kwargs):
                    if command[1] == "plan":
                        return json.dumps({"plan": plans[Path(command[2]).parent.name]})
                    return "".join(name + " hash-" + name + "\n" for name in command[1:])

                def run(command, **kwargs):
                    if command[1].endswith("accept-rpms.py"):
                        accepted = Path(command[command.index("--output") + 1])
                        accepted.mkdir(parents=True)
                        (accepted / "results.json").write_text('{"outcome":"passed"}')
                        return
                    if command[1] != "build":
                        return
                    name = Path(command[2]).parent.name
                    output = Path(command[command.index("--output") + 1])
                    arch = command[command.index("--arch") + 1]
                    calls.append(name)
                    self.assertFalse(list((root / ".work/python-deps" / arch / name).rglob(".complete")),
                                     "a rebuild must clear its old completion marker before execution")
                    evidence = output / "evidence" / arch
                    artifacts = evidence / "source/artifacts"
                    artifacts.mkdir(parents=True, exist_ok=True)
                    (artifacts / "upstream.sum").write_text(name + " results\n")
                    (evidence / "source/stderr.log").write_text(name + " diagnostic\n")
                    (output / "run-report.xml").write_text(f'<testsuite name="{name}" arch="{arch}"/>\n')
                    (output / "run-report.json").write_text(json.dumps({
                        "document": "rpmx-run-report", "version": 1,
                        "outcome": "failed" if name == failed_name else "passed",
                        "build_tests_requested": True,
                        "build_tests": [{"status": "failed" if name == failed_name else "passed"}],
                        "evidence": [str(evidence)],
                    }))
                    if name == failed_name:
                        raise subprocess.CalledProcessError(7, command)
                    binaries = output / arch
                    binaries.mkdir(exist_ok=True)
                    (binaries / (name + ".rpm")).write_text("private RPM")

                args = ["build-python.py", "python-demo", "--arch", "x86_64",
                        "--output", str(root / "out/python-demo"),
                        "--test-profile", str(root / "profiles/eternal.profile.yaml"),
                        "--test-reports", str(reports)]
                with patch.object(bootstrap, "__file__", str(root / "scripts/build-python.py")), \
                        patch.object(bootstrap, "bootstrap_recipes", return_value=recipes), \
                        patch.object(sys, "argv", args), \
                        patch.object(bootstrap.subprocess, "check_output", side_effect=capture), \
                        patch.object(bootstrap.subprocess, "run", side_effect=run):
                    if failed_name:
                        with self.assertRaises(subprocess.CalledProcessError) as failure:
                            bootstrap.main()
                        self.assertEqual(failure.exception.returncode, 7)
                        self.assertEqual(calls[-1], failed_name)
                    else:
                        bootstrap.main()
                        self.assertEqual(calls, list(plans))
                        shutil.rmtree(reports)
                        calls.clear()
                        dependency_cache = next((root / ".work/python-deps/x86_64/python-tool-a").iterdir())
                        variant = dependency_cache.name.rsplit("-", 1)[1]
                        hashes = bootstrap.bootstrap_hashes(list(plans), {name: "hash-" + name for name in plans})
                        stale = root / ".work/python-deps/x86_64/python-demo" / f"{hashes['python-demo']}-{variant}" / ".complete"
                        stale.parent.mkdir(parents=True)
                        stale.write_text("previous completion")
                        bootstrap.main()
                        self.assertFalse(stale.exists())
                        self.assertEqual(calls, ["python-demo"], "cached dependency reports must not require a rebuild")
                    expected = ["python-tool-a"] if failed_name == "python-tool-a" else ["python-tool-a", "python-tool-b"]
                    self.assertEqual(sorted(p.read_text().split()[0] for p in reports.rglob("upstream.sum")), sorted(expected))
                    self.assertEqual(len(list(reports.rglob("run-report.json"))), len(expected))
                    self.assertEqual(len(list(reports.rglob("stderr.log"))), len(expected))
                    self.assertFalse(list(reports.rglob("*.rpm")), "private dependency RPMs must stay private")
                    if failed_name != "python-tool-a":
                        self.assertEqual((root / "out/python-demo/evidence/x86_64/source/artifacts/upstream.sum").read_text(),
                                         "python-demo results\n")
                    if failed_name is None:
                        self.assertEqual(len(list(reports.rglob("acceptance/results.json"))), 2)
                        arm_args = args.copy()
                        arm_args[arm_args.index("--arch") + 1] = "aarch64"
                        with patch.object(sys, "argv", arm_args):
                            bootstrap.main()
                        for arch in ("x86_64", "aarch64"):
                            self.assertTrue((root / "out/python-demo/evidence" / arch / "source/artifacts/upstream.sum").is_file())
                            for report in (reports / "python/python-demo" / arch).rglob("run-report.xml"):
                                self.assertIn(f'arch="{arch}"', report.read_text())

    def test_evidence_copy_error_does_not_replace_the_build_failure(self):
        failure = subprocess.CalledProcessError(7, ["rpmx", "build"])
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(bootstrap.subprocess, "run", side_effect=failure), \
                patch.object(bootstrap, "collect_test_evidence", side_effect=OSError("disk full")), \
                patch.object(sys, "stderr", new_callable=io.StringIO) as diagnostics:
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                bootstrap.build_with_evidence(failure.cmd, Path(directory) / "output",
                                              Path(directory) / "reports", "x86_64", Path(directory))
        self.assertIs(raised.exception, failure)
        self.assertIn("cannot collect test evidence in", diagnostics.getvalue())
        self.assertIn("reports: disk full", diagnostics.getvalue())

    def test_source_and_installed_failures_keep_evidence_and_stop_the_gate(self):
        for failure_mode, expected_status in [("build-process", 7), ("source-report", 1), ("acceptance", 4)]:
            with self.subTest(failure_mode=failure_mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output, reports = root / "output", root / "reports"
                command, acceptance = ["rpmx", "build"], ["accept-rpms.py"]
                calls = []

                def run(actual, **kwargs):
                    calls.append(actual)
                    if actual == acceptance:
                        raise subprocess.CalledProcessError(4, actual)
                    artifacts = output / "evidence/source/artifacts"
                    artifacts.mkdir(parents=True)
                    (artifacts / "diagnostic.log").write_text("source diagnostics")
                    (output / "run-report.json").write_text(json.dumps({
                        "document": "rpmx-run-report", "version": 1,
                        "outcome": "failed" if failure_mode == "source-report" else "passed",
                        "build_tests_requested": True,
                        "build_tests": [{"status": "failed" if failure_mode == "source-report" else "passed"}],
                        "evidence": [str(output / "evidence")],
                    }))
                    if failure_mode == "build-process":
                        raise subprocess.CalledProcessError(7, actual)

                with patch.object(bootstrap.subprocess, "run", side_effect=run):
                    with self.assertRaises(subprocess.CalledProcessError) as failure:
                        bootstrap.build_with_evidence(command, output, reports, "x86_64", root, acceptance)
                self.assertEqual(failure.exception.returncode, expected_status)
                self.assertEqual(calls, [command, acceptance] if failure_mode == "acceptance" else [command])
                self.assertEqual((reports / "source/evidence/source/artifacts/diagnostic.log").read_text(),
                                 "source diagnostics")

    def test_omitted_optional_cases_are_not_fabricated_and_selected_failures_stop_promotion(self):
        for status in (None, "skipped", "failed", "not-run"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "output"
                acceptance = ["accept-rpms.py"]
                calls = []

                def run(command, **kwargs):
                    calls.append(command)
                    if command == acceptance:
                        return
                    output.mkdir()
                    report = {"document": "rpmx-run-report", "version": 1,
                              "outcome": "passed", "build_tests_requested": True,
                              "build_tests": [] if status is None else [{"status": status}],
                              "evidence": []}
                    (output / "run-report.json").write_text(json.dumps(report))

                with patch.object(bootstrap.subprocess, "run", side_effect=run):
                    if status is None:
                        bootstrap.build_with_evidence(["rpmx", "build"], output, None,
                                                      "x86_64", Path(directory), acceptance)
                        self.assertEqual(calls[-1], acceptance)
                        self.assertEqual(json.loads((output / "run-report.json").read_text())["build_tests"], [])
                    else:
                        with self.assertRaises(subprocess.CalledProcessError):
                            bootstrap.build_with_evidence(["rpmx", "build"], output, None,
                                                          "x86_64", Path(directory), acceptance)
                        self.assertNotIn(acceptance, calls)

    def test_malformed_evidence_does_not_replace_the_build_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            failure = subprocess.CalledProcessError(7, ["rpmx", "build"])

            def run(*args, **kwargs):
                output.mkdir(parents=True, exist_ok=True)
                (output / "run-report.json").write_text("partial report")
                raise failure

            with patch.object(bootstrap.subprocess, "run", side_effect=run), \
                    patch.object(sys, "stderr", new_callable=io.StringIO) as diagnostics:
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    bootstrap.build_with_evidence(failure.cmd, output, root / "reports", "x86_64", root)
            self.assertIs(raised.exception, failure)
            self.assertIn("cannot collect test evidence", diagnostics.getvalue())

    def test_setup_failure_cannot_publish_a_previous_successful_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, reports = root / "output", root / "reports"
            output.mkdir()
            (output / "run-report.json").write_text('{"outcome":"passed"}')
            (output / "run-report.xml").write_text("previous success")
            old_acceptance = output / "acceptance/x86_64"
            old_acceptance.mkdir(parents=True)
            (old_acceptance / "results.json").write_text("previous success")
            reports.mkdir()
            (reports / "run-report.xml").write_text("previous success")
            failure = subprocess.CalledProcessError(7, ["rpmx", "build"])
            with patch.object(bootstrap.subprocess, "run", side_effect=failure):
                with self.assertRaises(subprocess.CalledProcessError):
                    bootstrap.build_with_evidence(failure.cmd, output, reports, "x86_64", root)
            self.assertFalse((reports / "run-report.xml").exists())
            self.assertFalse((output / "run-report.json").exists())
            self.assertFalse(old_acceptance.exists())

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
