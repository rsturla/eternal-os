"""Candidate dependencies must be selected, tested, and included in cache keys."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CandidateBuilds(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        self.log = self.root / "calls.jsonl"
        self.env = dict(os.environ, CANDIDATE_CALLS=str(self.log))

    def executable(self, name, content):
        path = self.scripts / name
        path.write_text(content)
        path.chmod(0o755)
        return path

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_foundations_build_only_selected_names_in_dependency_order(self):
        shutil.copy2(ROOT / "scripts/build-test-dependencies.sh", self.scripts)
        self.executable("build-all.sh", r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
name = args[args.index('--package') + 1]
prior = []
if '--test-rpms' in args:
    prior = sorted(p.name for p in Path(args[args.index('--test-rpms') + 1]).glob('*.rpm'))
with open(os.environ['CANDIDATE_CALLS'], 'a') as log:
    log.write(json.dumps([name, prior, args]) + '\n')
output = Path(args[args.index('--output') + 1]) / name / args[args.index('--arch') + 1]
output.mkdir(parents=True)
(output / 'diagnostic.log').write_text('actual build diagnostic')
if os.environ.get('FAIL_FOUNDATION') == name:
    sys.exit(7)
(output / (name + '.rpm')).write_text(name)
(output / (name + '.src.rpm')).write_text('source')
''')
        command = [str(self.scripts / "build-test-dependencies.sh"),
                   "--package", "openssl3", "--package", "rpm", "--package", "kernel-headers",
                   "--arch", "x86_64", "--output", str(self.root / "out"),
                   "--rpms", str(self.root / "candidates")]
        subprocess.run(command, env=self.env, check=True, capture_output=True)
        self.assertEqual([call[:2] for call in self.calls()],
                         [["kernel-headers", []], ["rpm", ["kernel-headers.rpm"]],
                          ["openssl3", ["kernel-headers.rpm", "rpm.rpm"]]])
        self.assertEqual(sorted(p.name for p in (self.root / "candidates").iterdir()),
                         ["kernel-headers.rpm", "openssl3.rpm", "rpm.rpm"])

        # A failed predecessor must stop the chain and retain its diagnostic.
        self.log.unlink()
        shutil.rmtree(self.root / "out")
        shutil.rmtree(self.root / "candidates")
        result = subprocess.run(command, env=dict(self.env, FAIL_FOUNDATION="kernel-headers"),
                                capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual([call[0] for call in self.calls()], ["kernel-headers"])
        self.assertFalse(list((self.root / "candidates").iterdir()))
        self.assertTrue((self.root / "out/kernel-headers/x86_64/diagnostic.log").is_file())

    def test_candidate_payload_changes_invalidate_build_stamps(self):
        shutil.copy2(ROOT / "scripts/build-all.sh", self.scripts)
        shutil.copy2(ROOT / "scripts/accept-rpms.py", self.scripts)
        profile = self.root / "runtime.yaml"
        profile.write_text("runtime policy\n")
        recipe = self.root / "packages/openssf-compiler-options/package.yaml"
        recipe.parent.mkdir(parents=True)
        recipe.write_text("fixture")
        self.executable("package-hash.sh", "#!/bin/sh\nprintf '%s hash\\n' \"$1\"\n")
        self.executable("prepare-test-profile.py", r'''#!/usr/bin/env python3
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
for name in ('profile', 'rpms', 'arch', 'output'):
    p.add_argument('--' + name, required=True)
a = p.parse_args()
out = Path(a.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(Path(a.profile).read_text())
''')
        rpmx = self.executable("rpmx", r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
if a[0] == 'plan':
    print(json.dumps({'plan': {'cells': [{'id': 'default', 'tests': [{}]}]}}))
elif a[0] in ('build', 'test'):
    with open(os.environ['CANDIDATE_CALLS'], 'a') as log:
        log.write(json.dumps(a) + '\n')
    if a[0] == 'test':
        print(json.dumps({'document': 'rpmx-run-report', 'version': 1, 'outcome': 'passed',
                          'acceptance': 'completed', 'tests': [{'status': os.environ.get('CASE_STATUS', 'passed')}]}))
        sys.exit(0)
    out = Path(a[a.index('--output') + 1]) / 'x86_64'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'candidate.rpm').write_text('built')
    (out.parent / 'run-report.json').write_text(json.dumps({
        'document': 'rpmx-run-report', 'version': 1, 'outcome': 'passed',
        'build_tests_requested': True, 'build_tests': [], 'evidence': [],
    }))
    assert '--junit' not in a
    (out.parent / 'run-report.xml').write_text('<testsuite/>')
''')
        candidates = self.root / "input"
        candidates.mkdir()
        payload = candidates / "dependency.rpm"
        payload.write_text("first payload")
        command = [str(self.scripts / "build-all.sh"), "--package", "openssf-compiler-options",
                   "--arch", "x86_64", "--output", str(self.root / "out"),
                   "--test-profile", str(profile), "--test-rpms", str(candidates)]
        env = dict(self.env, RPMX=str(rpmx))
        for _ in range(2):
            subprocess.run(command, env=env, check=True, capture_output=True)
        self.assertEqual(len(self.calls()), 2, "unchanged candidate should use validated stamp")
        self.assertNotIn("--test-profile", self.calls()[0])
        first_profile = self.calls()[1][self.calls()[1].index("--test-profile") + 1]
        payload.write_text("changed payload")
        subprocess.run(command, env=env, check=True, capture_output=True)
        self.assertEqual(len(self.calls()), 4)
        last = self.calls()[-1]
        self.assertNotEqual(first_profile, last[last.index("--test-profile") + 1])
        self.assertNotIn("--profile", last, "candidate policy must not replace build policy")
        failed = subprocess.run(command + ["--force"], env=dict(env, CASE_STATUS="not-run"), capture_output=True)
        self.assertEqual(failed.returncode, 1)
        self.assertFalse((self.root / "out/.stamps/x86_64/openssf-compiler-options").exists())
        self.assertTrue((self.root / "out/openssf-compiler-options/x86_64/acceptance/results.json").exists())
        rejected = subprocess.run(command + ["--no-tests"], env=env, capture_output=True)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(len(self.calls()), 6)


if __name__ == "__main__":
    unittest.main()
