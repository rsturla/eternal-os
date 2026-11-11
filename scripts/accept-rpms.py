#!/usr/bin/env python3
"""Run standalone package acceptance and require complete passing evidence."""

import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("--install-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--test-profile", required=True, type=Path)
    parser.add_argument("--runner", default="auto")
    parser.add_argument("--build-release")
    args = parser.parse_args()
    rpmx = os.environ.get("RPMX", "rpmx")
    args.output.mkdir(parents=True, exist_ok=True)
    result = args.output / "results.json"
    result.unlink(missing_ok=True)
    (args.output / "junit.xml").unlink(missing_ok=True)
    evidence = args.output / "run"
    if evidence.exists():
        shutil.rmtree(evidence)
    plan_command = [rpmx, "plan", str(args.recipe), "--arch", args.arch, "--json"]
    if args.build_release:
        plan_command.extend(["--build-release", args.build_release])
    plan = json.loads(subprocess.check_output(plan_command, text=True))["plan"]
    expected = sum(len(cell["tests"]) for cell in plan["cells"])
    command = [rpmx, "test", str(args.recipe), "--install-dir", str(args.install_dir),
               "--arch", args.arch, "--runner", args.runner,
               "--test-profile", str(args.test_profile), "--test-output", str(evidence),
               "--junit", str(args.output / "junit.xml"), "--json"]
    if args.build_release:
        command.extend(["--build-release", args.build_release])
    with result.open("w") as stdout, (args.output / "run.log").open("w") as stderr:
        completed = subprocess.run(command, stdout=stdout, stderr=stderr)
    report = {}
    try:
        report = json.loads(result.read_text())
        if not isinstance(report, dict):
            raise TypeError("report must be an object")
        complete = (report["document"] == "rpmx-run-report" and report["version"] == 1
                    and report["outcome"] == "passed" and report["acceptance"] == "completed"
                    and len(report["tests"]) == expected
                    and all(case["status"] == "passed" for case in report["tests"]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"invalid acceptance report {result}: {error}", file=sys.stderr)
        complete = False
    if completed.returncode or not complete:
        # Raw report includes setup failures even when no command log exists.
        try:
            for diagnostic in [report.get("primary"), *report.get("secondary", [])]:
                if diagnostic:
                    print(f"{diagnostic['code']}: {diagnostic['message']}", file=sys.stderr)
            for case in report.get("tests", []):
                if case.get("status") != "passed":
                    print(f"{case.get('name')}: {case.get('status')}: {case.get('reason') or case.get('primary')}", file=sys.stderr)
        except (AttributeError, TypeError, KeyError):
            print(result.read_text(), file=sys.stderr)
        print((args.output / "run.log").read_text(), file=sys.stderr)
        raise SystemExit(completed.returncode or 1)
    print(f"==> acceptance evidence {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
