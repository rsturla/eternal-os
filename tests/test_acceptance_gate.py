"""Acceptance must be complete before artifacts become validated inputs."""

import json
import os
import selectors
import socket
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

    def test_optional_cases_are_required_only_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpmx = root / "rpmx"
            rpmx.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[0] == 'plan':
    tests = [{'optional': True}] if os.environ['ONLY_OPTIONAL'] == '1' else [{}, {'optional': True}]
    print(json.dumps({'plan': {'cells': [{'tests': tests}]}}))
else:
    assert os.environ['ONLY_OPTIONAL'] != '1', 'unselected optional cases must not run'
    assert ('--include-optional-tests' in args) == (os.environ['INCLUDE_OPTIONAL'] == '1')
    print(json.dumps({'document': 'rpmx-run-report', 'version': 1, 'outcome': 'passed',
                      'acceptance': 'completed', 'tests': json.loads(os.environ['CASES'])}))
''')
            rpmx.chmod(0o755)
            cases = [
                (False, False, [{"status": "passed"}], True),
                (True, False, [{"status": "passed"}, {"status": "passed"}], True),
                (True, False, [{"status": "passed"}], False),
                (True, False, [{"status": "passed"}, {"status": "skipped"}], False),
                (False, True, [], True),
            ]
            for include, only_optional, reported, succeeds in cases:
                with self.subTest(include=include, only_optional=only_optional, reported=reported):
                    output = root / "reports"
                    command = [str(ROOT / "scripts/accept-rpms.py"), "recipe.yaml",
                               "--install-dir", "rpms", "--output", str(output), "--arch", "x86_64"]
                    if include:
                        command.append("--include-optional-tests")
                    env = dict(os.environ, RPMX=str(rpmx), INCLUDE_OPTIONAL=str(int(include)),
                               ONLY_OPTIONAL=str(int(only_optional)), CASES=json.dumps(reported))
                    result = subprocess.run(command, env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, succeeds, result.stdout + result.stderr)
                    if only_optional:
                        self.assertIn("acceptance not requested", result.stderr)
                        self.assertFalse((output / "results.json").exists())

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


    def test_stderr_is_live_before_child_exit_without_waiting_for_a_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpmx = root / "rpmx"
            rpmx.write_text('''#!/usr/bin/env python3
import json, os, socket, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == 'plan':
    print(json.dumps({'plan': {'cells': [{'tests': [{}]}]}}))
else:
    sys.stderr.buffer.write(b'waiting-for-ack')
    sys.stderr.buffer.flush()
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(os.environ['ACK_SOCKET'])
        assert connection.recv(1) == b'A'
    Path(os.environ['CHILD_FINISHED']).touch()
    evidence = Path(args[args.index('--test-output') + 1])
    evidence.mkdir(parents=True)
    (evidence / 'receipt').write_text('retained artifact')
    Path(args[args.index('--junit') + 1]).write_text('<testsuite/>')
    print(json.dumps({'document': 'rpmx-run-report', 'version': 1, 'outcome': 'passed',
                      'acceptance': 'completed', 'tests': [{'status': 'passed'}]}))
''')
            rpmx.chmod(0o755)
            output = root / "reports"
            finished = root / "child-finished"
            marker = b"waiting-for-ack"
            with socket.socket(socket.AF_UNIX) as listener:
                address = str(root / "ack.sock")
                listener.bind(address)
                listener.listen(1)
                listener.settimeout(10)
                with subprocess.Popen([
                    str(ROOT / "scripts/accept-rpms.py"), "recipe.yaml",
                    "--install-dir", "rpms", "--output", str(output), "--arch", "x86_64",
                ], env=dict(os.environ, RPMX=str(rpmx), ACK_SOCKET=address,
                            CHILD_FINISHED=str(finished)), stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE) as process:
                    connection, _ = listener.accept()
                    try:
                        observed = b""
                        with selectors.DefaultSelector() as selector:
                            selector.register(process.stderr, selectors.EVENT_READ)
                            while len(observed) < len(marker):
                                self.assertTrue(selector.select(timeout=10),
                                                "child waits for acknowledgment: stderr must stream before exit")
                                chunk = os.read(process.stderr.fileno(), len(marker) - len(observed))
                                self.assertTrue(chunk, "acceptance stderr closed before progress arrived")
                                observed += chunk
                        self.assertEqual(observed, marker)
                        self.assertIsNone(process.poll())
                        self.assertFalse(finished.exists(), "output must arrive before child completion")
                        self.assertEqual((output / "run.log").read_bytes(), marker)
                    finally:
                        # Release the child even when the old non-streaming implementation fails.
                        connection.sendall(b'A')
                        connection.close()
                        stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 0, stderr)
                    self.assertEqual(stdout, b"", "the child JSON belongs in results.json")
            self.assertTrue(finished.exists())
            self.assertEqual((output / "run.log").read_bytes(), marker)
            self.assertEqual((output / "run/receipt").read_text(), "retained artifact")
            self.assertTrue((output / "junit.xml").is_file())
            self.assertEqual(json.loads((output / "results.json").read_text())["outcome"], "passed")

    def test_failed_child_preserves_exact_stderr_once_and_nonzero_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rpmx = root / "rpmx"
            rpmx.write_text('''#!/usr/bin/env python3
import json, sys
if sys.argv[1] == 'plan':
    print(json.dumps({'plan': {'cells': [{'tests': [{}]}]}}))
else:
    # Even a complete report cannot override the process's failure status.
    print(json.dumps({'document': 'rpmx-run-report', 'version': 1, 'outcome': 'passed',
                      'acceptance': 'completed', 'tests': [{'status': 'passed'}]}))
    sys.stderr.buffer.write(b'worker failed: \\xff\\rpartial')
    sys.stderr.buffer.flush()
    sys.exit(23)
''')
            rpmx.chmod(0o755)
            output = root / "reports"
            result = subprocess.run([
                str(ROOT / "scripts/accept-rpms.py"), "recipe.yaml",
                "--install-dir", "rpms", "--output", str(output), "--arch", "x86_64",
            ], env=dict(os.environ, RPMX=str(rpmx)), capture_output=True)
            expected = b"worker failed: \xff\rpartial"
            self.assertEqual(result.returncode, 23)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, expected, "stderr must be streamed exactly once")
            self.assertEqual((output / "run.log").read_bytes(), expected)
            self.assertEqual(json.loads((output / "results.json").read_text())["outcome"], "passed")


if __name__ == "__main__":
    unittest.main()
