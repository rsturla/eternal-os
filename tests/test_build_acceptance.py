"""Build entry points require standalone acceptance before marking success."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class BuildAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        (self.root / "bin").mkdir()
        (self.root / "profiles").mkdir()
        (self.root / "profiles/eternal.profile.yaml").write_text(yaml.safe_dump({"repositories": [{"id": "eternal", "baseurl": "https://example.invalid"}]}))
        for name in ("build-all.sh", "build-python.py", "accept-rpms.py"):
            shutil.copy2(ROOT / "scripts" / name, self.root / "scripts" / name)
        for name in ("demo", "openssf-compiler-options", "python-3.15", "python-tool", "python-demo"):
            recipe = self.root / "packages" / name / "package.yaml"
            recipe.parent.mkdir(parents=True)
            recipe.write_text(yaml.safe_dump({"matrix": {"axes": {"python": ["3.15"]}}}))
        self.executable(self.root / "scripts/package-hash.sh", "#!/bin/sh\nfor name do printf '%s hash\\n' \"$name\"; done\n")
        self.executable(self.root / "bin/rpmx", r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
import yaml
args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1]
name = Path(args[1]).parent.name if args[0] in ('plan', 'build', 'test') else None
if args[0] == 'plan':
    output = {'python-tool':'python-3.15-tool', 'python-demo':'python-3.15-demo'}.get(name, name)
    cell = {'packages':['python-3.15'] if name == 'python-demo' else [], 'sysroot':[],
            'pipeline':[], 'build_tests':[], 'tests':[{'packages':['python-3.15-tool'] if name == 'python-demo' else []}],
            'outputs':[{'name':output, 'requires':['python-3.15'] if name == 'python-tool' else [], 'provides':[]}]}
    print(json.dumps({'plan':{'cells':[cell]}}))
    sys.exit(0)
entry = {'command':args[0], 'name':name, 'args':args}
profile_flag = '--test-profile' if args[0] == 'test' else '--profile'
if profile_flag in args:
    entry['profile'] = yaml.safe_load(Path(value(profile_flag)).read_text())
if args[0] == 'repo':
    entry['rpms'] = sorted(path.name for path in Path(value('--rpms')).glob('*.rpm'))
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps(entry) + '\n')
if args[0] == 'build':
    output = Path(value('--output'))
    arch = value('--arch') if '--arch' in args else 'x86_64'
    (output / arch).mkdir(parents=True, exist_ok=True)
    rpm = output / arch / (name + '.rpm')
    rpm.write_text('production RPM')
    (output / 'evidence').mkdir(exist_ok=True)
    (output / 'evidence/source.log').write_text('source suite evidence')
    (output / 'run-report.json').write_text(json.dumps({'artifacts':{'rpms':[str(rpm)]}}))
    if os.environ.get('SOURCE_FAIL') == name:
        sys.exit(7)
elif args[0] == 'test':
    evidence = Path(value('--test-output'))
    evidence.mkdir(parents=True)
    (evidence / 'consumer.log').write_text('acceptance evidence')
    Path(value('--junit')).write_text('<testsuite/>')
    cases = [] if os.environ.get('MISSING_ACCEPT') == name else [{'status':'not-run' if os.environ.get('SKIP_ACCEPT') == name else 'passed'}]
    print(json.dumps({'document':'rpmx-run-report', 'version':1, 'outcome':'passed',
                      'acceptance':'completed', 'tests':cases}))
elif args[0] == 'repo':
    metadata = Path(value('--output')) / 'repodata'
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / 'repomd.xml').write_text('repository metadata')
''')
        self.env = dict(os.environ, RPMX=str(self.root / "bin/rpmx"), CALLS=str(self.root / "calls.jsonl"),
                        PATH=str(self.root / "bin") + os.pathsep + os.environ["PATH"])

    def executable(self, path, contents):
        path.write_text(contents)
        path.chmod(0o755)

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def build(self, *extra, env=None):
        return subprocess.run([str(self.root / "scripts/build-all.sh"), "--package", "demo", "--arch", "x86_64",
                               "--output", str(self.root / "out"), *extra], env=env or self.env,
                              capture_output=True, text=True)

    def test_build_accepts_package_against_published_compiler_policy(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([(call["command"], call["name"]) for call in self.calls()],
                         [("build", "demo"), ("test", "demo")])
        self.assertTrue((self.root / "out/.stamps/x86_64/demo").exists())
        self.assertTrue((self.root / "out/demo/evidence/source.log").exists())
        self.assertTrue((self.root / "out/demo/acceptance/x86_64/run/consumer.log").exists())
        before = self.calls()
        self.assertEqual(self.build().returncode, 0)
        self.assertEqual(self.calls(), before)

    def test_missing_or_skipped_acceptance_prevents_stamp_even_on_forced_rebuild(self):
        self.assertEqual(self.build().returncode, 0)
        for variable in ("MISSING_ACCEPT", "SKIP_ACCEPT"):
            result = self.build("--force", env=dict(self.env, **{variable: "demo"}))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / "out/.stamps/x86_64/demo").exists())
            self.assertTrue((self.root / "out/demo/acceptance/x86_64/results.json").exists())

    def test_source_failure_retains_logs_and_cannot_leave_stale_acceptance_or_stamp(self):
        self.assertEqual(self.build().returncode, 0)
        result = self.build("--force", env=dict(self.env, SOURCE_FAIL="demo"))
        self.assertEqual(result.returncode, 7)
        self.assertFalse((self.root / "out/.stamps/x86_64/demo").exists())
        self.assertFalse((self.root / "out/demo/acceptance").exists())
        self.assertTrue((self.root / "out/demo/evidence/source.log").exists())

    def python_build(self, *extra, env=None):
        profile = self.root / "profiles/bootstrap-python.profile.yaml"
        profile.parent.mkdir(exist_ok=True)
        profile.write_text(yaml.safe_dump({"repositories":[{"id":"fedora", "baseurl":"https://example.invalid"}]}))
        return subprocess.run(["python3", str(self.root / "scripts/build-python.py"), "python-demo",
                               "--arch", "x86_64", "--output", str(self.root / "out"), *extra],
                              env=env or self.env, capture_output=True, text=True)

    def test_python_accepts_test_tool_dependencies_before_private_repo_promotion(self):
        result = self.python_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([(call["command"], call["name"]) for call in self.calls()],
                         [("build", "python-3.15"), ("test", "python-3.15"), ("repo", None),
                          ("build", "python-tool"), ("test", "python-tool"), ("repo", None),
                          ("build", "python-demo"), ("test", "python-demo"), ("repo", None)])
        test = next(call for call in self.calls() if call["command"] == "test" and call["name"] == "python-tool")
        self.assertEqual(test["profile"]["repositories"][0]["id"], "python-local")

    def test_python_failed_acceptance_never_marks_or_promotes_dependency(self):
        result = self.python_build(env=dict(self.env, SKIP_ACCEPT="python-tool"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call["rpms"] for call in self.calls() if call["command"] == "repo"], [["python-3.15.rpm"]])
        self.assertFalse(list((self.root / ".work/python-deps/x86_64/python-tool").rglob(".complete")))
        self.assertFalse(any(call["name"] == "python-demo" for call in self.calls()))

    def test_explicit_no_tests_skips_acceptance_and_case_only_python_tools(self):
        result = self.python_build("--no-tests")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(call["command"] == "test" for call in self.calls()))
        self.assertEqual([call["name"] for call in self.calls() if call["command"] == "build"], ["python-3.15", "python-demo"])

    def test_deferred_mode_keeps_source_tests_and_requires_separate_cache_stamp(self):
        result = self.build('--defer-acceptance', '--build-release', '123')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(call['command'] == 'test' for call in self.calls()))
        self.assertTrue(all('--no-tests' not in call['args'] for call in self.calls()))
        policy = self.root / 'out/demo/x86_64/build-policy.json'
        self.assertEqual(json.loads(policy.read_text()), {'build_release': '123'})
        before = self.calls()
        self.assertEqual(self.build('--defer-acceptance', '--build-release', '456').returncode, 0)
        self.assertEqual(self.calls(), before)
        self.assertEqual(json.loads(policy.read_text())['build_release'], '123')
        self.assertEqual(self.build().returncode, 0)
        self.assertTrue(any(call['command'] == 'test' for call in self.calls()))

    def test_deferred_mode_rejects_disabling_source_tests_before_any_work(self):
        result = self.build('--defer-acceptance', '--no-tests')
        self.assertEqual(result.returncode, 2)
        self.assertIn('--defer-acceptance requires source tests', result.stderr)
        self.assertFalse((self.root / 'calls.jsonl').exists())
        self.assertFalse((self.root / 'out').exists())
        self.assertFalse((self.root / '.work').exists())

    def test_deferred_source_failure_does_not_stamp_or_run_acceptance(self):
        result = self.build('--defer-acceptance', env=dict(self.env, SOURCE_FAIL='demo'))
        self.assertEqual(result.returncode, 7)
        self.assertFalse((self.root / 'out/.stamps/x86_64/demo').exists())
        self.assertFalse(any(call['command'] == 'test' for call in self.calls()))
        self.assertTrue((self.root / 'out/demo/evidence/source.log').exists())


if __name__ == "__main__":
    unittest.main()
