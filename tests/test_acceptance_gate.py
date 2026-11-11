"""Acceptance must be complete before artifacts become validated inputs."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceGate(unittest.TestCase):
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
