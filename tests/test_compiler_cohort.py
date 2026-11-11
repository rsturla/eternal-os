"""Producer candidates must pass the complete production acceptance gate before use."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class CompilerCohort(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("scripts", "profiles", "bin"):
            (self.root / name).mkdir()
        for script in ("compiler-cohort.py", "prepare-test-profile.py", "accept-rpms.py"):
            shutil.copy2(ROOT / "scripts" / script, self.root / "scripts" / script)
        for name in ("openssf-compiler-options", "gcc-13", "gcc-14"):
            path = self.root / "packages" / name
            path.mkdir(parents=True)
            (path / "package.yaml").write_text(name)
        (self.root / ".rpmx-revision").write_text("fixture-revision\n")
        bootstrap = {"document": "rpmx-profile", "archs": ["x86_64", "aarch64"],
                     "repositories": [{"id": "eternal", "baseurl": "https://example.invalid", "exclude": ["gcc-*", "libgcc-*"]},
                                      {"id": "eternal-toolchain", "baseurl": "file://../.work/toolchain-repo"},
                                      {"id": "local", "baseurl": "file://../other", "gpgkey": "file://keys/key.asc"}]}
        (self.root / "profiles/bootstrap.profile.yaml").write_text(yaml.safe_dump(bootstrap))
        production = {"document": "rpmx-profile", "archs": ["x86_64", "aarch64"],
                      "packages": {"install": ["unselected-seed"]},
                      "repositories": [{"id": "eternal", "baseurl": "https://example.invalid/rolling"}]}
        (self.root / "profiles/eternal.profile.yaml").write_text(yaml.safe_dump(production))
        self.executable(self.root / "scripts/package-hash.sh", '''#!/usr/bin/env python3
import hashlib, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
name = sys.argv[1]
print(name, hashlib.sha256((root / 'packages' / name / 'package.yaml').read_bytes()).hexdigest())
''')
        self.executable(self.root / "bin/rpm", '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
metadata = json.loads(Path(sys.argv[-1]).read_text())
if sys.argv[-3] == '%{SOURCEPACKAGE}':
    print(metadata.get('sourcepackage', '0'))
else:
    print('\\n'.join(str(metadata.get(key, '0')) for key in ('name','epochnum','version','release','arch','sourcepackage')))
''')
        self.executable(self.root / "bin/rpmx", '''#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
import yaml
args = sys.argv[1:]
def value(flag, default=None):
    return args[args.index(flag)+1] if flag in args else default
name = Path(args[1]).parent.name if args[0] in ('plan', 'build', 'test') else None
arch = value('--arch', 'x86_64')
release = '2.eternal' + ('+build' + value('--build-release') if value('--build-release') else '')
outputs = [] if name is None else ([name] if name == 'openssf-compiler-options' else [name, 'libgcc-' + name.split('-')[1]])
if args[0] == 'plan':
    print(json.dumps({'plan': {'cells': [{'version':'1', 'release':release,
        'outputs':[{'name': output, 'arch':'noarch' if name == 'openssf-compiler-options' else arch} for output in outputs],
        'build_tests': [] if name == 'openssf-compiler-options' else [{}], 'tests':[{}]}]}}))
    sys.exit(0)
with open(os.environ['COHORT_CALLS'], 'a') as log:
    entry = {'args':args, 'name':name}
    if '--profile' in args:
        entry['profile'] = yaml.safe_load(Path(value('--profile')).read_text())
    if '--test-profile' in args:
        entry['test_profile'] = yaml.safe_load(Path(value('--test-profile')).read_text())
    log.write(json.dumps(entry) + '\\n')
if args[0] == 'build':
    assert '--no-tests' not in args
    out = Path(value('--output'))
    (out / arch).mkdir(parents=True)
    for output in outputs:
        (out / arch / (output + '.rpm')).write_text(json.dumps({'name':output, 'epochnum':'0', 'version':'1', 'release':release, 'arch':'noarch' if name == 'openssf-compiler-options' else arch}))
    source = out / arch / 'src' / (name + '.src.rpm')
    source.parent.mkdir()
    source.write_text(json.dumps({'sourcepackage':'1'}))
    count = 0 if name == 'openssf-compiler-options' else 1
    (out / 'run-report.json').write_text(json.dumps({'document':'rpmx-run-report', 'version':1, 'outcome':'passed', 'build_tests_requested':True, 'artifacts':{'rpms':[str(out / arch / (output + '.rpm')) for output in outputs], 'srpms':[str(source)]},
        'build_tests':[{'status':'not-run' if os.environ.get('SOURCE_NOT_RUN') == name else 'passed'}] * count}))
    (out / 'evidence').mkdir()
    (out / 'evidence/unrelated.rpm').write_text('diagnostic, never a consumer candidate')
    if os.environ.get('CHANGE_SOURCE') == name:
        Path(args[1]).write_text('changed during build')
    print('retained source diagnostic')
    if os.environ.get('FAIL_PRODUCER') == name:
        sys.exit(7)
elif args[0] == 'repo':
    out = Path(value('--output'))
    (out / 'repodata').mkdir(parents=True)
    (out / 'repodata/repomd.xml').write_text('<repomd/>')
    for rpm in Path(value('--rpms')).glob('*.rpm'):
        shutil.copy2(rpm, out / rpm.name)
elif args[0] == 'test':
    failed = os.environ.get('FAIL_ACCEPT') == name
    print(json.dumps({'document':'rpmx-run-report', 'version':1, 'outcome':'incomplete' if failed else 'passed',
        'acceptance':'completed', 'tests':[{'status':'not-run' if failed else 'passed'}]}))
''')
        self.env = dict(os.environ, RPMX=str(self.root / "bin/rpmx"),
                        PATH=str(self.root / "bin") + os.pathsep + os.environ["PATH"],
                        COHORT_CALLS=str(self.root / "calls.jsonl"))
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()

    def executable(self, path, text):
        path.write_text(text)
        path.chmod(0o755)

    def run_helper(self, command, *arguments, env=None):
        return subprocess.run(["python3", str(self.root / "scripts/compiler-cohort.py"), command,
                               "--arch", "x86_64", *map(str, arguments)],
                              env=self.env if env is None else env, text=True, capture_output=True)

    def produce(self, *names):
        seed = self.inputs / "openssf-compiler-options"
        result = self.run_helper("produce-seed", "--output", seed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in names:
            result = self.run_helper("produce", "--package", name, "--seed", seed, "--output", self.inputs / name)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def accept(self, *names, env=None):
        args = [item for name in names for item in ("--package", name)]
        return self.run_helper("accept", *args, "--inputs", self.inputs,
                               "--output", self.root / "out", "--rpms", self.root / "verified", env=env)

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def test_selected_producers_use_one_private_seed_and_full_production_acceptance(self):
        self.produce("gcc-13", "gcc-14")
        result = self.accept("gcc-13", "gcc-14")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        builds = [call for call in self.calls() if call["args"][0] == "build"]
        self.assertEqual([call["name"] for call in builds], ["openssf-compiler-options", "gcc-13", "gcc-14"])
        self.assertNotIn("--profile", builds[0]["args"])
        profile = builds[1]["profile"]
        self.assertEqual(profile["repositories"][0]["exclude"], ["gcc-*", "libgcc-*", "openssf-compiler-options"])
        self.assertIn("/inputs/gcc-13/seed-repository", profile["repositories"][1]["baseurl"])
        self.assertEqual(profile["repositories"][2]["baseurl"], "file://" + str(self.root / "other"))
        self.assertEqual(profile["repositories"][2]["gpgkey"], "file://" + str(self.root / "profiles/keys/key.asc"))
        tests = [call for call in self.calls() if call["args"][0] == "test"]
        self.assertEqual([call["name"] for call in tests], ["openssf-compiler-options", "gcc-13", "gcc-14"])
        self.assertTrue(all(call["test_profile"]["repositories"][1]["baseurl"] == "https://example.invalid/rolling" for call in tests))
        self.assertTrue(all(call["test_profile"]["packages"]["install"] == ["unselected-seed"] for call in tests))
        self.assertEqual({path.name for path in (self.root / "verified").iterdir()},
                         {"gcc-13.rpm", "libgcc-13.rpm", "gcc-14.rpm", "libgcc-14.rpm"})
        self.assertEqual({str(path.relative_to(self.root / "out/gcc-13"))
                          for path in (self.root / "out/gcc-13").rglob("*.rpm")},
                         {"x86_64/gcc-13.rpm", "x86_64/libgcc-13.rpm", "x86_64/src/gcc-13.src.rpm"})
        self.assertFalse((self.root / "out/.stamps").exists())
        self.assertTrue((self.root / "out/gcc-13/run-report.json").is_file())
        self.assertTrue((self.root / "out/test-reports/compiler-cohort/x86_64/gcc-13/results.json").exists())

    def test_later_acceptance_failure_never_promotes_any_cohort_member(self):
        self.produce("gcc-13", "gcc-14")
        result = self.accept("gcc-13", "gcc-14", env=dict(self.env, FAIL_ACCEPT="gcc-14"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "verified").exists())
        self.assertFalse((self.root / "out/gcc-13").exists())
        self.assertTrue((self.root / "out/test-reports/compiler-cohort/x86_64/gcc-14/results.json").exists())

    def test_failed_or_not_run_source_suite_has_no_valid_producer_manifest(self):
        for variable in ("FAIL_PRODUCER", "SOURCE_NOT_RUN"):
            destination = self.root / variable
            self.produce()
            result = self.run_helper("produce", "--package", "gcc-13", "--seed", self.inputs / "openssf-compiler-options",
                                     "--output", destination, env=dict(self.env, **{variable: "gcc-13"}))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((destination / "producer.json").exists())
            self.assertIn("retained source diagnostic", (destination / "build.log").read_text())
            shutil.rmtree(self.inputs / "openssf-compiler-options")

    def test_tampered_or_wrong_seed_inputs_fail_before_acceptance(self):
        self.produce("gcc-13")
        manifest = self.inputs / "gcc-13/producer.json"
        record = json.loads(manifest.read_text())
        record["seed_manifest"] = "wrong-seed"
        manifest.write_text(json.dumps(record))
        result = self.accept("gcc-13")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different seed", result.stderr)
        self.assertFalse(any(call["args"][0] == "test" for call in self.calls()))
        record["seed_manifest"] = hashlib.sha256((self.inputs / "openssf-compiler-options/producer.json").read_bytes()).hexdigest()
        manifest.write_text(json.dumps(record))
        (self.inputs / "gcc-13/build/x86_64/libgcc-13.rpm").write_text("changed")
        result = self.accept("gcc-13")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("files changed", result.stderr)
        self.assertFalse((self.root / "verified").exists())

    def refresh_manifest(self, name):
        directory = self.inputs / name
        path = directory / "producer.json"
        record = json.loads(path.read_text())
        record["files"] = {str(item.relative_to(directory)): hashlib.sha256(item.read_bytes()).hexdigest()
                           for item in directory.rglob("*") if item.is_file() and item != path}
        path.write_text(json.dumps(record))

    def test_source_change_during_build_cannot_stamp_old_bytes_with_new_identity(self):
        destination = self.inputs / "openssf-compiler-options"
        result = self.run_helper("produce-seed", "--output", destination,
                                 env=dict(self.env, CHANGE_SOURCE="openssf-compiler-options"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity changed during the build", result.stderr)
        self.assertFalse((destination / "producer.json").exists())
        self.assertTrue((destination / "build.log").exists())

    def test_colliding_binary_filenames_cannot_overwrite_a_verified_candidate(self):
        self.produce("gcc-13", "gcc-14")
        for name in ("gcc-13", "gcc-14"):
            directory = self.inputs / name
            original = directory / "build/x86_64" / (name + ".rpm")
            renamed = original.with_name("candidate.rpm")
            original.rename(renamed)
            report_path = directory / "build/run-report.json"
            report = json.loads(report_path.read_text())
            report["artifacts"]["rpms"][0] = str(renamed)
            report_path.write_text(json.dumps(report))
            self.refresh_manifest(name)
        result = self.accept("gcc-13", "gcc-14")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate candidate filename", result.stderr)
        self.assertFalse(any(call["args"][0] == "test" for call in self.calls()))
        self.assertFalse((self.root / "verified").exists())

    def test_coherent_manifest_cannot_hide_missing_or_unreported_binary_outputs(self):
        self.produce("gcc-13")
        directory = self.inputs / "gcc-13"
        path = directory / "build/x86_64/libgcc-13.rpm"
        saved = path.read_bytes()
        path.unlink()
        self.refresh_manifest("gcc-13")
        result = self.accept("gcc-13")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreported or missing RPM", result.stderr)
        path.write_bytes(saved)
        path.with_name("unreported.rpm").write_bytes(saved)
        self.refresh_manifest("gcc-13")
        result = self.accept("gcc-13")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreported or missing RPM", result.stderr)
        self.assertFalse(any(call["args"][0] == "test" for call in self.calls()))

    def test_local_foundation_entrypoint_builds_only_selected_compiler_once(self):
        shutil.copy2(ROOT / "scripts/build-test-dependencies.sh", self.root / "scripts")
        result = subprocess.run([str(self.root / "scripts/build-test-dependencies.sh"),
                                 "--package", "gcc-13", "--arch", "x86_64",
                                 "--output", str(self.root / "out"), "--rpms", str(self.root / "verified")],
                                env=dict(self.env, TMPDIR=str(self.root)), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([call["name"] for call in self.calls() if call["args"][0] == "build"],
                         ["openssf-compiler-options", "gcc-13"])
        self.assertEqual([call["name"] for call in self.calls() if call["args"][0] == "test"],
                         ["openssf-compiler-options", "gcc-13"])
        self.assertEqual({path.name for path in (self.root / "verified").iterdir()},
                         {"gcc-13.rpm", "libgcc-13.rpm"})
        self.assertFalse((self.root / "out/openssf-compiler-options").exists())

    def test_workflow_plan_selects_compilers_once_and_keeps_unrelated_changes_small(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/_build-packages.yml").read_text())
        script = next(step["run"] for step in workflow["jobs"]["prepare"]["steps"] if step.get("id") == "plan")
        selections = [("gcc-13", "openssf-compiler-options", "glibc-2.44", "curl"),
                      ("glibc-2.44", "curl")]
        for selected in selections:
            with self.subTest(selected=selected):
                for name in selected:
                    recipe = self.root / "packages" / name / "package.yaml"
                    recipe.parent.mkdir(parents=True, exist_ok=True)
                    recipe.write_text(name)
                self.executable(self.root / "scripts/list-packages.sh",
                                "#!/bin/sh\nprintf '%s\\n' " + " ".join(selected) + "\n")
                output = self.root / "workflow-outputs"
                output.write_text("")
                subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=self.root,
                               env=dict(self.env, SELECTION="all", BASE_REF="", GITHUB_OUTPUT=str(output)),
                               check=True, capture_output=True, text=True)
                values = dict(line.split("=", 1) for line in output.read_text().splitlines())
                self.assertEqual(json.loads(values["compilers"]), [name for name in selected if name.startswith("gcc-")])
                foundations = json.loads(values["foundations"])
                consumers = json.loads(values["consumers"])
                self.assertEqual(sorted(foundations + consumers), sorted(selected))
                self.assertFalse(set(foundations) & set(consumers))
                self.assertEqual(consumers, ["curl"])


if __name__ == "__main__":
    unittest.main()
