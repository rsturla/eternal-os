"""A cached routine build must not satisfy a request for optional tests."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OptionalBuildTests(unittest.TestCase):
    def test_opt_in_rebuilds_and_reaches_both_test_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(ROOT / "scripts/build-all.sh", scripts)
            hashing = scripts / "package-hash.sh"
            hashing.write_text("#!/bin/sh\necho 'openssf-compiler-options unchanged-hash'\n")
            hashing.chmod(0o755)
            recipe = root / "packages/openssf-compiler-options/package.yaml"
            recipe.parent.mkdir(parents=True)
            recipe.touch()
            log = root / "calls.jsonl"
            driver = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['CALL_LOG']).open('a') as log:
    log.write(json.dumps(args) + '\\n')
if args[0] == 'build':
    output = Path(args[args.index('--output') + 1])
    rpm = output / 'x86_64/fixture.rpm'
    rpm.parent.mkdir(parents=True, exist_ok=True)
    rpm.write_bytes(b'fixture')
    (output / 'run-report.json').write_text(json.dumps({'artifacts': {'rpms': [str(rpm)]}}))
'''
            rpmx = root / "rpmx"
            rpmx.write_text(driver)
            rpmx.chmod(0o755)
            (scripts / "accept-rpms.py").write_text(driver)
            command = [str(scripts / "build-all.sh"), "--package", "openssf-compiler-options",
                       "--arch", "x86_64", "--output", str(root / "out")]
            env = dict(os.environ, RPMX=str(rpmx), CALL_LOG=str(log))
            for optional in (False, False, True, True, False):
                args = command + (["--include-optional-tests"] if optional else [])
                result = subprocess.run(args, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 6, calls)
            for index, optional in enumerate((False, True, False)):
                build, acceptance = calls[index * 2:index * 2 + 2]
                self.assertEqual(build[0], "build")
                self.assertEqual("--include-optional-tests" in build, optional)
                self.assertEqual("--include-optional-tests" in acceptance, optional)
            result = subprocess.run(command + ["--include-optional-tests", "--no-tests"],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot be combined", result.stderr)
            self.assertEqual(len(log.read_text().splitlines()), 6)


if __name__ == "__main__":
    unittest.main()
