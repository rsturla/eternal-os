"""The local runtime entry point uses CI's pool and strict acceptance gate."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeReports(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ('test-all.sh', 'accept-rpms.py', 'candidate-pool.py'):
            shutil.copy2(ROOT / 'scripts' / name, scripts)
        recipe = self.root / 'packages/demo/package.yaml'
        recipe.parent.mkdir(parents=True)
        recipe.write_text('fixture recipe\n')
        (self.root / '.rpmx-revision').write_text('fixture revision\n')
        self.subject = self.root / 'rpms/demo/x86_64'
        self.subject.mkdir(parents=True)
        (self.subject / 'demo-1-1.x86_64.rpm').write_text('subject')
        (self.subject / 'build-policy.json').write_text('{"build_release":42}')
        (self.subject / 'demo.src.rpm').write_text('source')
        nested = self.subject / 'test-results/fixture.x86_64.rpm'
        nested.parent.mkdir()
        nested.write_text('private fixture')
        self.dependency = self.root / 'rpms/dependency/x86_64'
        self.dependency.mkdir(parents=True)
        (self.dependency / 'dependency-1-1.noarch.rpm').write_text('dependency')
        (self.dependency / 'build-policy.json').write_text('{"build_release":null}')
        foreign = self.root / 'rpms/dependency/aarch64'
        foreign.mkdir()
        (foreign / 'dependency-1-1.aarch64.rpm').write_text('foreign')
        self.rpmx = self.root / 'rpmx'
        self.rpmx.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
assert sys.argv[sys.argv.index('--build-release') + 1] == '42'
with Path(os.environ['CALLS']).open('a') as log:
    log.write(sys.argv[1] + '\\n')
if sys.argv[1] == 'plan':
    mode = os.environ.get('MODE')
    if mode in ('invalid', 'invalid-json'):
        diagnostic = 'RPMX-TEST-004: invalid fixture declaration'
        if mode == 'invalid-json':
            print(json.dumps({'ok': False, 'diagnostics': [diagnostic]}))
        else:
            print(diagnostic, file=sys.stderr)
        sys.exit(2)
    tests = [] if mode == 'zero' else [{'name': 'mandatory'}]
    if mode in ('mixed', 'optional-failed', 'optional-skipped'):
        tests.append({'name': 'optional', 'optional': True})
    if mode == 'optional-only':
        tests = [{'name': 'optional', 'optional': True}]
    print(json.dumps({'plan': {'cells': [{'tests': tests}]}}))
else:
    source = Path(sys.argv[sys.argv.index('--install-dir') + 1])
    payloads = sorted(path.read_text() for path in source.glob('*.rpm'))
    if os.environ.get('POOLED') == '1':
        assert payloads == ['dependency', 'subject'], payloads
    else:
        assert source == Path(os.environ['OWN_DIRECTORY']), source
    if os.environ.get('MODE') == 'preparation':
        print(json.dumps({'document':'rpmx-run-report', 'version':1, 'outcome':'failed',
            'acceptance':'running', 'tests':[], 'primary':{'code':'RPMX-ROOT-002',
            'message':'builder image digest differs from the lock'}}))
        sys.exit(1)
    status = 'skipped' if os.environ.get('MODE') == 'skipped' else 'passed'
    tests = [{'name': 'mandatory', 'status': status}]
    if '--include-optional-tests' in sys.argv:
        if os.environ.get('MODE') == 'optional-only':
            tests = []
        if os.environ.get('MODE') in ('mixed', 'optional-only', 'optional-failed', 'optional-skipped'):
            optional_status = {'optional-failed':'failed', 'optional-skipped':'skipped'}.get(os.environ.get('MODE'), 'passed')
            tests.append({'name': 'optional', 'status': optional_status})
    print(json.dumps({'document':'rpmx-run-report', 'version':1, 'outcome':'passed',
                     'acceptance':'completed', 'tests':tests}))
''')
        self.rpmx.chmod(0o755)

    def run_entry(self, mode='passed', pooled=True, include_optional=False):
        command = [str(self.root / 'scripts/test-all.sh'), '--package', 'demo',
                   '--rpms', str(self.root / 'rpms'), '--output', str(self.root / 'reports'),
                   '--arch', 'x86_64']
        if include_optional:
            command.append('--include-optional-tests')
        if pooled:
            command.extend(['--candidate-rpms', str(self.root / 'rpms')])
        return subprocess.run(command, env=dict(os.environ, RPMX=str(self.rpmx), MODE=mode,
                              POOLED=str(int(pooled)), OWN_DIRECTORY=str(self.subject),
                              CALLS=str(self.root / 'calls')), capture_output=True, text=True)

    def test_preparation_error_is_printed_and_retained_with_canonical_pool(self):
        result = self.run_entry('preparation')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('RPMX-ROOT-002', result.stderr)
        self.assertIn('builder image digest differs from the lock', result.stderr)
        report = json.loads((self.root / 'reports/demo/x86_64/results.json').read_text())
        self.assertEqual(report['outcome'], 'failed')
        self.assertIn('demo\tx86_64\tfailed\t', (self.root / 'reports/results.tsv').read_text())

    def test_own_directory_and_optional_pool_preserve_actual_build_release(self):
        for pooled in (False, True):
            with self.subTest(pooled=pooled):
                result = self.run_entry(pooled=pooled)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('demo\tx86_64\tpassed\t', (self.root / 'reports/results.tsv').read_text())

    def test_zero_skipped_and_missing_subjects_cannot_report_success(self):
        for mode in ('zero', 'skipped'):
            with self.subTest(mode=mode):
                result = self.run_entry(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.subject / 'demo-1-1.x86_64.rpm').unlink()
        result = self.run_entry(pooled=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing binary RPMs', result.stderr)

    def test_optional_selection_matches_the_runtime_report(self):
        for include_optional in (False, True):
            with self.subTest(include_optional=include_optional):
                result = self.run_entry('mixed', include_optional=include_optional)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((self.root / 'reports/demo/x86_64/results.json').read_text())
                self.assertEqual([case['name'] for case in report['tests']],
                                 ['mandatory', 'optional'] if include_optional else ['mandatory'])

    def test_selected_optional_failure_or_skip_fails_the_gate(self):
        for mode in ('optional-failed', 'optional-skipped'):
            with self.subTest(mode=mode):
                result = self.run_entry(mode, include_optional=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('demo\tx86_64\tfailed\t', (self.root / 'reports/results.tsv').read_text())

    def test_optional_only_default_rejects_without_running_acceptance(self):
        result = self.run_entry('optional-only')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['plan'])
        self.assertFalse((self.root / 'reports/demo/x86_64/results.json').exists())
        self.assertIn('no installed-package tests selected', result.stderr)
        self.assertNotIn('\tpassed\t', (self.root / 'reports/results.tsv').read_text())
        opted_in = self.run_entry('optional-only', include_optional=True)
        self.assertEqual(opted_in.returncode, 0, opted_in.stdout + opted_in.stderr)

    def test_invalid_plan_diagnostic_is_visible_and_retained(self):
        for mode, evidence in [('invalid', 'run.log'), ('invalid-json', 'plan.json')]:
            with self.subTest(mode=mode):
                (self.root / 'calls').unlink(missing_ok=True)
                result = self.run_entry(mode)
                self.assertNotEqual(result.returncode, 0)
                diagnostic = 'RPMX-TEST-004: invalid fixture declaration'
                self.assertIn(diagnostic, result.stderr)
                self.assertIn(diagnostic, (self.root / 'reports/demo/x86_64' / evidence).read_text())
                self.assertEqual((self.root / 'calls').read_text().splitlines(), ['plan'])

    def test_duplicate_pool_members_fail_before_any_rpmx_call(self):
        (self.dependency / 'demo-1-1.x86_64.rpm').write_text('conflicting subject')
        result = self.run_entry()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate candidate filename', result.stderr)
        self.assertFalse((self.root / 'calls').exists())


if __name__ == '__main__':
    unittest.main()
