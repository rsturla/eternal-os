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

    def test_unpublished_test_tools_are_built_before_the_consumer(self):
        consumer = plan("python-3.15-demo")
        consumer["cells"][0]["tests"] = [{
            "packages": ["python-3.15-installer"],
            "pipeline": [{"needs": ["python-3.15-wheel"]}],
        }]
        plans = {
            "python-demo": consumer,
            "python-installer": plan("python-3.15-installer"),
            "python-wheel": plan("python-3.15-wheel"),
        }
        order = bootstrap.dependency_order(plans, "python-demo")
        self.assertLess(order.index("python-installer"), order.index("python-demo"))
        self.assertLess(order.index("python-wheel"), order.index("python-demo"))
        self.assertEqual(
            bootstrap.dependency_order(plans, "python-demo", include_tests=False),
            ["python-demo"],
        )

    def test_main_prepares_test_dependencies_and_relocates_both_profiles(self):
        for no_tests in (False, True):
            with self.subTest(no_tests=no_tests), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "scripts").mkdir()
                (root / "profiles/repo").mkdir(parents=True)
                (root / "profiles/key file.asc").write_text("public key")
                policy = {"repositories": [{
                    "id": "published", "baseurl": "file://repo",
                    "gpgkey": "file://key%20file.asc",
                }]}
                for name in ("bootstrap-python.profile.yaml", "runtime.yaml"):
                    (root / "profiles" / name).write_text(yaml.safe_dump(policy))
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
                    if command[1] != "build":
                        return
                    name = Path(command[2]).parent.name
                    generated = yaml.safe_load(Path(command[command.index("--profile") + 1]).read_text())
                    policies = [generated]
                    if no_tests:
                        self.assertNotIn("--test-profile", command)
                        self.assertNotIn("--junit", command)
                        self.assertIn("--no-tests", command)
                    else:
                        runtime = Path(command[command.index("--test-profile") + 1])
                        policies.append(yaml.safe_load(runtime.read_text()))
                    for settings in policies:
                        published = next(r for r in settings["repositories"] if r["id"] == "published")
                        self.assertEqual(published["baseurl"], f"file://{root / 'profiles/repo'}")
                        self.assertEqual(published["gpgkey"], f"file://{root / 'profiles/key file.asc'}")
                        self.assertTrue(Path(published["gpgkey"][7:]).is_file())
                        if name == "python-demo" and not no_tests:
                            self.assertEqual(settings["repositories"][0]["id"], "python-local")
                            self.assertIn("python-3.15-tool", published["exclude"])
                    builds.append(name)
                    output = Path(command[command.index("--output") + 1]) / "x86_64"
                    output.mkdir(parents=True, exist_ok=True)
                    (output / (name + ".rpm")).write_text("fixture RPM")

                args = ["build-python.py", "python-demo",
                        "--arch", "x86_64", "--output", str(root / "out"),
                        "--test-profile", str(root / "profiles/runtime.yaml")]
                if no_tests:
                    args.append("--no-tests")
                with patch.object(bootstrap, "__file__", str(root / "scripts/build-python.py")), \
                        patch.object(sys, "argv", args), \
                        patch.object(bootstrap.subprocess, "check_output", side_effect=capture), \
                        patch.object(bootstrap.subprocess, "run", side_effect=run):
                    bootstrap.main()
                    actual_builds = builds.copy()
                    with patch.object(sys, "argv", [*args, "--fingerprint"]), redirect_stdout(io.StringIO()) as first:
                        bootstrap.main()
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
                    if command[1] != "build":
                        return
                    name = Path(command[2]).parent.name
                    junit = Path(command[command.index("--junit") + 1])
                    calls.append((name, junit))
                    output = Path(command[command.index("--output") + 1])
                    arch = command[command.index("--arch") + 1]
                    artifacts = output / arch / "test-results/assertion/artifacts"
                    artifacts.mkdir(parents=True)
                    (artifacts / "upstream.sum").write_text(name + " results\n")
                    (artifacts.parent / "stderr.log").write_text(name + " diagnostic\n")
                    junit.write_text(f'<testsuite name="{name}" arch="{arch}"/>\n')
                    if name == failed_name:
                        raise subprocess.CalledProcessError(7, command)
                    (output / arch / (name + ".rpm")).write_text("private RPM")

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
                        self.assertEqual(calls[-1][0], failed_name)
                    else:
                        bootstrap.main()
                        self.assertEqual([name for name, _ in calls], list(plans))
                        self.assertEqual(len({path for _, path in calls}), 3)
                        # A new report destination must include evidence from
                        # cached dependencies, without rebuilding them.
                        shutil.rmtree(reports)
                        calls.clear()
                        bootstrap.main()
                        self.assertEqual([name for name, _ in calls], ["python-demo"])
                    summaries = sorted(reports.rglob("upstream.sum"))
                    expected = [failed_name] if failed_name == "python-tool-a" else ["python-tool-a", "python-tool-b"]
                    self.assertEqual(sorted(p.read_text().split()[0] for p in summaries), sorted(expected))
                    self.assertEqual(len(list(reports.rglob("junit.xml"))), len(expected))
                    self.assertEqual(len(list(reports.rglob("stderr.log"))), len(expected))
                    self.assertFalse(list(reports.rglob("*.rpm")), "private dependency RPMs must stay private")
                    if failed_name != "python-tool-a":
                        public = root / "out/python-demo"
                        self.assertIn('name="python-demo"', (public / "x86_64/junit.xml").read_text())
                        self.assertEqual((public / "x86_64/test-results/assertion/artifacts/upstream.sum").read_text(),
                                         "python-demo results\n")
                    if failed_name is None:
                        # Reusing one output root for another architecture must
                        # preserve the first report, including cached inputs.
                        arm_args = args.copy()
                        arm_args[arm_args.index("--arch") + 1] = "aarch64"
                        with patch.object(sys, "argv", arm_args):
                            bootstrap.main()
                        self.assertIn('arch="x86_64"', (public / "x86_64/junit.xml").read_text())
                        self.assertIn('arch="aarch64"', (public / "aarch64/junit.xml").read_text())
                        calls.clear()
                        bootstrap.main()
                        self.assertEqual([name for name, _ in calls], ["python-demo"])
                        for arch in ("x86_64", "aarch64"):
                            self.assertIn(f'arch="{arch}"', (public / arch / "junit.xml").read_text())
                            for report in (reports / "python/python-demo" / arch).rglob("junit.xml"):
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

    def test_setup_failure_cannot_publish_a_previous_successful_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, reports = root / "output", root / "reports"
            old = output / "x86_64/test-results/old"
            old.mkdir(parents=True)
            (old / "stdout.log").write_text("previous success")
            (output / "x86_64/junit.xml").write_text("previous success")
            reports.mkdir()
            (reports / "junit.xml").write_text("previous success")
            failure = subprocess.CalledProcessError(7, ["rpmx", "build"])
            with patch.object(bootstrap.subprocess, "run", side_effect=failure):
                with self.assertRaises(subprocess.CalledProcessError):
                    bootstrap.build_with_evidence(failure.cmd, output, reports, "x86_64", root)
            self.assertFalse(reports.exists())
            self.assertFalse((output / "x86_64/junit.xml").exists())
            self.assertFalse(old.exists())

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


class BuildAllCache(unittest.TestCase):
    def test_cache_tracks_test_policy_profiles_and_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            (root / "profiles").mkdir()
            (root / "profiles/bootstrap.profile.yaml").write_text("archs: [aarch64, x86_64]\n")
            original = Path(__file__).resolve().parents[1] / "scripts/build-all.sh"
            shutil.copy2(original, scripts / "build-all.sh")
            for name in ("demo", "openssf-compiler-options"):
                recipe = root / "packages" / name / "package.yaml"
                recipe.parent.mkdir(parents=True)
                recipe.write_text("fixture recipe")
            helpers = {
                "package-hash.sh": r"""#!/usr/bin/env bash
for name in "$@"; do
  printf '%s hash-%s\n' "$name" "$name"
done
""",
            }
            for name, source in helpers.items():
                path = scripts / name
                path.write_text(source)
                path.chmod(0o755)
            stub = root / "rpmx"
            stub.write_text(r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['BUILD_CACHE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
if args[0] == 'plan':
    cell = 'python=3.15' if os.environ.get('BUILD_CACHE_MATRIX') else 'default'
    print(json.dumps({'plan': {'cells': [{'id': cell}]}}))
elif args[0] == 'build':
    output = Path(args[args.index('--output') + 1])
    arch = args[args.index('--arch') + 1]
    name = Path(args[1]).parent.name
    if name == os.environ.get('BUILD_CACHE_EARLY_FAIL') and arch == os.environ.get('BUILD_CACHE_EARLY_FAIL_ARCH', arch):
        sys.exit(7)
    (output / arch).mkdir(parents=True, exist_ok=True)
    (output / arch / 'fixture.rpm').write_text('fixture RPM')
    if '--junit' in args:
        junit = Path(args[args.index('--junit') + 1])
        junit.write_text('<testsuite name="' + name + '" arch="' + arch + '"/>\n')
        evidence = output / arch / 'test-results/assertion/artifacts'
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / 'upstream.sum').write_text(name + ' results\n')
        # A different architecture's old evidence must not enter this report.
        other_arch = 'aarch64' if arch == 'x86_64' else 'x86_64'
        foreign = output / other_arch / 'test-results/assertion/artifacts'
        foreign.mkdir(parents=True, exist_ok=True)
        (foreign / 'upstream.sum').write_text('wrong-architecture results\n')
    if os.environ.get('BUILD_CACHE_BREAK_EVIDENCE'):
        for report in Path(os.environ['BUILD_CACHE_BREAK_EVIDENCE']).glob('toolchain/*'):
            (report / arch).write_text('block evidence directory creation')
    if name == os.environ.get('BUILD_CACHE_FAIL'):
        sys.exit(7)
elif args[0] == 'repo':
    output = Path(args[args.index('--output') + 1]) / 'repodata'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'repomd.xml').write_text('fixture metadata')
""")
            stub.chmod(0o755)
            log = root / "calls.jsonl"
            profiles = []
            for name in ("first", "second"):
                path = root / name / "runtime.yaml"
                path.parent.mkdir()
                path.write_text("repositories: [{baseurl: 'file://repo'}]\n")
                profiles.append(path)
            env = dict(os.environ, RPMX=str(stub), BUILD_CACHE_LOG=str(log))

            def build(profile, *, arch="x86_64", no_tests=False, force=False):
                log.write_text("")
                command = [str(scripts / "build-all.sh"), "--package", "demo",
                           "--output", str(root / "out"), "--arch", arch,
                           "--test-profile", str(profile)]
                if no_tests:
                    command.append("--no-tests")
                if force:
                    command.append("--force")
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return [call for call in map(json.loads, log.read_text().splitlines()) if call[0] == "build"]

            def expect_builds(count, profile, reason, **options):
                calls = build(profile, **options)
                with self.subTest(scenario=reason):
                    self.assertEqual(len(calls), count, reason)
                return calls

            expect_builds(2, profiles[0], "build seed and consumer without tests", no_tests=True)
            expect_builds(0, profiles[0], "reuse an unchanged untested build", no_tests=True)
            tested = expect_builds(2, profiles[0], "enabling tests must invalidate both stamps")
            self.assertEqual(len({call[call.index("--junit") + 1] for call in tested}), 2)
            summaries = list((root / "out/test-reports").rglob("upstream.sum"))
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].read_text(), "openssf-compiler-options results\n")
            self.assertTrue((root / "out/demo/x86_64/junit.xml").is_file())
            expect_builds(0, profiles[0], "reuse an unchanged tested build")
            # Evidence collection errors on cache hits must fail explicitly.
            seed_report = next((root / "out/test-reports/toolchain").iterdir())
            shutil.rmtree(seed_report / "x86_64")
            (seed_report / "x86_64").write_text("block cached report copy")
            result = subprocess.run([
                str(scripts / "build-all.sh"), "--package", "demo", "--arch", "x86_64",
                "--output", str(root / "out"), "--test-profile", str(profiles[0]),
            ], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("cannot collect test evidence in", result.stderr)
            (seed_report / "x86_64").unlink()
            expect_builds(0, profiles[0], "restore cached reports without rebuilding")
            # Identical YAML under a different directory has different relative paths.
            expect_builds(2, profiles[1], "a relocated profile changes relative repository paths")
            profiles[1].write_text("repositories: [{baseurl: 'file://another-repo'}]\n")
            expect_builds(2, profiles[1], "changed repositories must invalidate both stamps")
            expect_builds(2, profiles[1], "an architecture change rebuilds both packages", arch="aarch64")
            expect_builds(0, profiles[1], "reuse the unchanged aarch64 build", arch="aarch64")
            expect_builds(1, profiles[1], "cached x86 build preserves its report after an arm build")
            for target in ("x86_64", "aarch64"):
                self.assertIn(f'arch="{target}"', (root / "out/demo" / target / "junit.xml").read_text())
            expect_builds(1, profiles[1], "restore the arm seed without rebuilding the consumer", arch="aarch64")
            # A bare recipe hash does not prove this architecture or test policy.
            (root / ".work/toolchain-repo/.stamp").write_text("hash-openssf-compiler-options\n")
            calls = expect_builds(1, profiles[1], "an incomplete seed stamp must rebuild the seed", arch="aarch64")
            self.assertIn("openssf-compiler-options", calls[0][1])

            # A failed source suite must still publish its log artifacts. A
            # failed seed stops before the consumer; a failed consumer retains
            # both reports. Neither failure may become a successful stamp.
            for failed_name, copy_error in [("openssf-compiler-options", False),
                                            ("demo", False),
                                            ("openssf-compiler-options", True)]:
                with self.subTest(failed_build=failed_name, copy_error=copy_error):
                    (root / ".work/toolchain-repo/.stamp").unlink(missing_ok=True)
                    env["BUILD_CACHE_FAIL"] = failed_name
                    failed_output = root / ("failed-" + failed_name + ("-copy-error" if copy_error else ""))
                    if copy_error:
                        env["BUILD_CACHE_BREAK_EVIDENCE"] = str(failed_output / "test-reports")
                    result = subprocess.run([
                        str(scripts / "build-all.sh"), "--package", "demo",
                        "--output", str(failed_output), "--arch", "x86_64",
                        "--test-profile", str(profiles[0]),
                    ], env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                    summaries = list((failed_output / "test-reports").rglob("upstream.sum"))
                    expected = ["openssf-compiler-options"]
                    self.assertEqual(sorted(p.read_text().split()[0] for p in summaries),
                                     [] if copy_error else sorted(expected))
                    self.assertEqual(len(list((failed_output / "test-reports").rglob("junit.xml"))), len(expected))
                    self.assertFalse(list((failed_output / "test-reports").rglob("*.rpm")))
                    self.assertFalse((failed_output / ".stamps/x86_64/demo").exists())
                    if failed_name == "demo":
                        self.assertEqual((failed_output / "demo/x86_64/test-results/assertion/artifacts/upstream.sum").read_text(),
                                         "demo results\n")
                        self.assertTrue((failed_output / "demo/x86_64/junit.xml").is_file())
                    if copy_error:
                        self.assertIn("cannot collect test evidence in", result.stderr)
                        del env["BUILD_CACHE_BREAK_EVIDENCE"]
            del env["BUILD_CACHE_FAIL"]
            # Restore the architecture used by the matrix cache scenarios.
            expect_builds(1, profiles[1], "restore the aarch64 seed after failed-build checks", arch="aarch64")

            env["BUILD_CACHE_EARLY_FAIL"] = "demo"
            result = subprocess.run([
                str(scripts / "build-all.sh"), "--package", "demo", "--force",
                "--output", str(root / "out"), "--arch", "aarch64",
                "--test-profile", str(profiles[1]),
            ], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            self.assertFalse((root / "out/demo/aarch64/junit.xml").exists())
            self.assertFalse((root / "out/demo/aarch64/test-results").exists())
            self.assertFalse((root / "out/.stamps/aarch64/demo").exists())
            del env["BUILD_CACHE_EARLY_FAIL"]

            (root / ".work/toolchain-repo/.stamp").unlink(missing_ok=True)
            calls = expect_builds(4, profiles[1], "all expands the profile's architecture order", arch="all", force=True)
            self.assertEqual([call[call.index("--arch") + 1] for call in calls],
                             ["aarch64", "aarch64", "x86_64", "x86_64"])
            for target in ("aarch64", "x86_64"):
                self.assertIn(f'arch="{target}"', (root / "out/demo" / target / "junit.xml").read_text())
            env.update(BUILD_CACHE_EARLY_FAIL="demo", BUILD_CACHE_EARLY_FAIL_ARCH="aarch64")
            log.write_text("")
            result = subprocess.run([
                str(scripts / "build-all.sh"), "--package", "demo", "--force", "--arch", "all",
                "--output", str(root / "out"), "--test-profile", str(profiles[1]),
            ], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            calls = [call for call in map(json.loads, log.read_text().splitlines())
                     if call[0] == "build" and Path(call[1]).parent.name == "demo"]
            self.assertEqual([call[call.index("--arch") + 1] for call in calls], ["aarch64", "x86_64"])
            self.assertFalse((root / "out/demo/aarch64/junit.xml").exists())
            self.assertIn('arch="x86_64"', (root / "out/demo/x86_64/junit.xml").read_text())
            del env["BUILD_CACHE_EARLY_FAIL"], env["BUILD_CACHE_EARLY_FAIL_ARCH"]
            expect_builds(2, profiles[1], "restore arm after its failed all-architecture build", arch="aarch64")

            # A matrix consumer must check its local dependency identity before
            # the outer stamp can skip the Python bootstrap helper.
            env["BUILD_CACHE_MATRIX"] = "1"
            dependency = root / "local-dependency.hash"
            dependency.write_text("first-local-test-tool")
            (scripts / "build-python.py").write_text(r"""import json, os, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(__file__).resolve().parents[1]
if '--fingerprint' in args:
    print((root / 'local-dependency.hash').read_text())
else:
    with open(os.environ['BUILD_CACHE_LOG'], 'a') as log:
        log.write(json.dumps(['build', 'matrix-helper', *args]) + '\n')
    output = Path(args[args.index('--output') + 1]) / args[args.index('--arch') + 1]
    output.mkdir(parents=True, exist_ok=True)
    (output / 'fixture.rpm').write_text('matrix fixture RPM')
""")
            (root / "out/.stamps/aarch64/demo").unlink()
            expect_builds(1, profiles[1], "build the matrix consumer with a local test tool", arch="aarch64")
            expect_builds(0, profiles[1], "reuse an unchanged matrix dependency closure", arch="aarch64")
            dependency.write_text("changed-local-test-tool")
            expect_builds(1, profiles[1], "a changed local test tool must rebuild its consumer", arch="aarch64")



if __name__ == "__main__":
    unittest.main()
