"""Acceptance must be complete before artifacts become validated inputs."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceGate(unittest.TestCase):
    def test_no_declared_acceptance_retains_plan_without_claiming_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpmx = root / "rpmx"
            rpmx.write_text('''#!/usr/bin/env python3
import json, sys
assert sys.argv[1] == 'plan', 'a source-only recipe must not invoke standalone tests'
print(json.dumps({'plan': {'cells': [{'tests': []}]}}))
''')
            rpmx.chmod(0o755)
            output = root / "reports"
            output.mkdir()
            (output / "results.json").write_text('{"outcome": "passed"}')
            result = subprocess.run([
                str(ROOT / "scripts/accept-rpms.py"), "recipe.yaml",
                "--install-dir", "rpms", "--output", str(output), "--arch", "x86_64",
            ], env=dict(os.environ, RPMX=str(rpmx)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("acceptance not requested", result.stderr)
            self.assertTrue((output / "plan.json").is_file())
            self.assertFalse((output / "results.json").exists())

    def test_runtime_profile_is_default_and_explicit_profile_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = root / "package.yaml"
            recipe.write_text("build:\n  root:\n    profile: bootstrap.profile.yaml\n")
            (root / "bootstrap.profile.yaml").write_text(
                "repositories:\n  - id: eternal\n    exclude: [eternal-baselayout]\n")
            private = root / "private.profile.yaml"
            private.write_text("repositories:\n  - id: python-local\n")
            rpmx = root / "rpmx"
            rpmx.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == 'plan':
    print(json.dumps({'plan': {'cells': [{'tests': [{}]}]}}))
else:
    # Omitting the explicit profile would inherit the recipe's bootstrap policy.
    assert '--test-profile' in args, 'runtime profile must override build exclusions'
    selected = Path(args[args.index('--test-profile') + 1]).resolve()
    assert selected == Path(os.environ['EXPECTED_PROFILE']).resolve(), selected
    assert selected.is_file(), selected
    Path(args[args.index('--junit') + 1]).write_text('<testsuite/>')
    print(json.dumps({'document':'rpmx-run-report', 'version':1, 'outcome':'passed',
                      'acceptance':'completed', 'tests':[{'status':'passed'}]}))
''')
            rpmx.chmod(0o755)
            for profile in (None, private):
                with self.subTest(profile=profile):
                    expected = profile or ROOT / "profiles/eternal.profile.yaml"
                    command = [str(ROOT / "scripts/accept-rpms.py"), str(recipe),
                               "--install-dir", "rpms", "--output", str(root / "reports"),
                               "--arch", "x86_64"]
                    if profile:
                        command.extend(["--test-profile", str(profile)])
                    result = subprocess.run(command, env=dict(os.environ, RPMX=str(rpmx),
                                            EXPECTED_PROFILE=str(expected)), capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_complete_report_required_even_when_process_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpmx = root / "rpmx"
            rpmx.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == 'plan':
    print(json.dumps({'plan': {'cells': [{'tests': [{}, {}]}]}}))
else:
    assert '--install-dir' in args and '--test-profile' in args
    assert '--root-lock' not in args
    assert '--root' not in args
    Path(args[args.index('--junit') + 1]).write_text('<testsuite/>')
    print(os.environ['REPORT'])
''')
            rpmx.chmod(0o755)
            base = {"document": "rpmx-run-report", "version": 1, "outcome": "passed",
                    "acceptance": "completed", "tests": [{"status": "passed"}, {"status": "passed"}]}
            cases = [("complete", base, True),
                     ("missing case", dict(base, tests=[{"status": "passed"}]), False),
                     ("skipped", dict(base, tests=[{"status": "passed"}, {"status": "skipped"}]), False),
                     ("not run", dict(base, tests=[{"status": "passed"}, {"status": "not-run"}]), False),
                     ("running", dict(base, acceptance="running"), False),
                     ("incomplete", dict(base, outcome="incomplete"), False)]
            for name, report, expected in cases:
                with self.subTest(name=name):
                    output = root / "reports"
                    stale = output / "run/old/artifact"
                    stale.parent.mkdir(parents=True, exist_ok=True)
                    stale.write_text("previous success")
                    result = subprocess.run([
                        str(ROOT / "scripts/accept-rpms.py"), "recipe.yaml",
                        "--install-dir", "rpms", "--output", str(output),
                        "--arch", "x86_64", "--test-profile", "profile.yaml",
                    ], env=dict(os.environ, RPMX=str(rpmx), REPORT=json.dumps(report)),
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)
                    self.assertEqual(json.loads((output / "results.json").read_text()), report)
                    self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
