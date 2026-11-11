"""Runtime test preparation failures must be visible without downloading reports."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeReports(unittest.TestCase):
    def test_preparation_error_is_printed_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(ROOT / "scripts/test-all.sh", scripts)
            shutil.copy2(ROOT / "scripts/accept-rpms.py", scripts)
            recipe = root / "packages/demo/package.yaml"
            recipe.parent.mkdir(parents=True)
            recipe.write_text("fixture recipe\n")
            (root / ".rpmx-revision").write_text("fixture revision\n")
            rpms = root / "rpms/demo/x86_64"
            rpms.mkdir(parents=True)
            (rpms / "demo.rpm").write_text("fixture payload\n")
            rpmx = root / "rpmx"
            rpmx.write_text('''#!/usr/bin/env python3
import json, sys
if sys.argv[1] == 'plan':
    print(json.dumps({'plan': {'cells': [{'tests': [{}]}]}}))
else:
    print(json.dumps({'document': 'rpmx-run-report', 'version': 1, 'outcome': 'failed', 'acceptance': 'running', 'tests': [], 'primary': {
        'code': 'RPMX-ROOT-002', 'message': 'builder image digest differs from the lock',
    }}))
    sys.exit(1)
''')
            rpmx.chmod(0o755)
            result = subprocess.run([
                str(scripts / "test-all.sh"), "--package", "demo",
                "--rpms", str(root / "rpms"), "--output", str(root / "reports"),
                "--arch", "x86_64",
            ], env=dict(os.environ, RPMX=str(rpmx)), capture_output=True, text=True)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("RPMX-ROOT-002", result.stderr)
            self.assertIn("builder image digest differs from the lock", result.stderr)
            report = json.loads((root / "reports/demo/x86_64/results.json").read_text())
            self.assertEqual(report["outcome"], "failed")
            self.assertIn("demo\tx86_64\tfailed\t", (root / "reports/results.tsv").read_text())


if __name__ == "__main__":
    unittest.main()
