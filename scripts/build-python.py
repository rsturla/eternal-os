#!/usr/bin/env python3
"""Prepare unpublished Python dependencies during the initial bootstrap.

Explicit bootstrap support for unpublished interpreter streams. Retain it
until rpmx can prepare unpublished source dependencies.
Track removal at https://github.com/rsturla/eternal-os/issues/41.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import yaml


def bootstrap_recipes(root):
    """Include every interpreter stream and every Python matrix recipe."""
    for recipe in sorted((root / "packages").glob("python-*/package.yaml")):
        data = yaml.safe_load(recipe.read_text())
        axes = data.get("matrix", {}).get("axes", {})
        if "python" in axes or re.fullmatch(r"python-\d+\.\d+", recipe.parent.name):
            yield recipe


def dependency_order(plans, name, *, include_tests=True, include_optional_tests=False):
    providers = {
        output["name"]: source
        for source, plan in plans.items()
        for cell in plan["cells"]
        for output in cell["outputs"]
    }
    order, visiting, visited = [], set(), set()

    def visit(source):
        if source in visiting:
            raise SystemExit(f"Python build dependency cycle at {source}")
        if source in visited:
            return
        visiting.add(source)
        dependencies = set()
        for cell in plans[source]["cells"]:
            for field in ("packages", "sysroot"):
                dependencies.update(cell.get(field, []))
            for step in cell["pipeline"]:
                dependencies.update(step["needs"])
            for output in cell["outputs"]:
                dependencies.update(output["requires"])
            if include_tests:
                for case in [*cell.get("build_tests", []), *cell.get("tests", [])]:
                    if case.get("optional", False) and not include_optional_tests:
                        continue
                    dependencies.update(case.get("packages", []))
                    for step in case.get("pipeline", []):
                        dependencies.update(step.get("needs", []))
        for dependency in sorted(dependencies):
            provider = providers.get(dependency.split()[0])
            if provider and provider != source:
                visit(provider)
        visiting.remove(source)
        visited.add(source)
        order.append(source)

    visit(name)
    return order


def bootstrap_hashes(order, hashes):
    """Invalidate a local bootstrap build when an earlier input changes."""
    result = {}
    inputs = []
    for name in order:
        inputs.append((name, hashes[name]))
        result[name] = hashlib.sha256(json.dumps(inputs).encode()).hexdigest()
    return result


def collect_test_evidence(output, destination, arch):
    """Mirror current source reports and their declared evidence, never RPM outputs."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("run-report.json", "run-report.xml"):
        source = output / name
        if source.is_file():
            shutil.copy2(source, destination / name)
    report_path = output / "run-report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text())
        for evidence in report.get("evidence", []):
            source = Path(evidence).resolve()
            relative = source.relative_to(output.resolve())
            target = destination / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            elif source.is_file():
                shutil.copy2(source, target)
            else:
                raise FileNotFoundError(f"declared source evidence is missing: {source}")
    acceptance = output / "acceptance" / arch
    if acceptance.is_dir():
        shutil.copytree(acceptance, destination / "acceptance", dirs_exist_ok=True)
    print(f"==> test evidence {destination}", file=sys.stderr)


def build_with_evidence(command, output, destination, arch, root, acceptance=None):
    """Keep native reports on failures and prevent stale reports from passing the gate."""
    for name in ("run-report.json", "run-report.xml"):
        (output / name).unlink(missing_ok=True)
    shutil.rmtree(output / "acceptance" / arch, ignore_errors=True)
    if destination is not None and destination.exists():
        shutil.rmtree(destination)
    failure = None
    try:
        subprocess.run(command, check=True, cwd=root)
        report = json.loads((output / "run-report.json").read_text())
        if (report["document"] != "rpmx-run-report" or report["version"] != 1
                or report["outcome"] != "passed" or not report["build_tests_requested"]
                or any(case["status"] != "passed" for case in report["build_tests"])):
            raise subprocess.CalledProcessError(1, command)
        if acceptance is not None:
            subprocess.run(acceptance, check=True, cwd=root)
    except subprocess.CalledProcessError as error:
        failure = error
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"invalid build report in {output}: {error}", file=sys.stderr)
        failure = subprocess.CalledProcessError(1, command)
    try:
        if destination is not None:
            collect_test_evidence(output, destination, arch)
        else:
            print(f"==> test evidence {output}", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"cannot collect test evidence in {destination}: {error}", file=sys.stderr)
        if failure is None:
            raise
    if failure is not None:
        raise failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--output", required=True)
    parser.add_argument("--arch", default=os.uname().machine)
    parser.add_argument("--test-reports", type=Path,
                        help="Collect dependency reports here; default: OUTPUT/test-reports")
    parser.add_argument("--fingerprint", action="store_true",
                        help="Print the local dependency and test policy identity without building")
    parser.add_argument("--profile", type=Path, help="Bootstrap profile for the new interpreter stream")
    parser.add_argument("--test-profile", type=Path,
                        default=Path(__file__).resolve().parent.parent / "profiles/eternal.profile.yaml",
                        help="Repository profile for installed tests")
    args, build_args = parser.parse_known_args()
    include_optional_tests = "--include-optional-tests" in build_args
    if include_optional_tests and "--no-tests" in build_args:
        parser.error("--include-optional-tests cannot be combined with --no-tests")
    if args.arch == "all":
        parser.error("Python dependency bootstrap requires one concrete --arch; run each architecture separately")
    root = Path(__file__).resolve().parent.parent
    rpmx = os.environ.get("RPMX", "rpmx")

    def capture(*command):
        return subprocess.check_output(command, cwd=root, text=True)

    plans = {
        recipe.parent.name: json.loads(capture(rpmx, "plan", str(recipe), "--arch", args.arch, "--json"))["plan"]
        for recipe in bootstrap_recipes(root)
    }
    include_tests = "--no-tests" not in build_args
    order = dependency_order(plans, args.name, include_tests=include_tests,
                             include_optional_tests=include_optional_tests)
    hashes = dict(line.split() for line in capture(
        str(root / "scripts/package-hash.sh"), *order
    ).splitlines())
    hashes = bootstrap_hashes(order, hashes)
    profile_path = (args.profile or root / "profiles/bootstrap-python.profile.yaml").resolve()
    profile = yaml.safe_load(profile_path.read_text())
    test_profile_path = args.test_profile.resolve()
    test_profile = yaml.safe_load(test_profile_path.read_text())
    variant = hashlib.sha256(json.dumps([
        build_args, str(profile_path), profile, str(test_profile_path), test_profile,
    ], sort_keys=True).encode()).hexdigest()[:12]
    if args.fingerprint:
        print(hashlib.sha256(json.dumps([
            args.arch, hashes[args.name], variant,
        ]).encode()).hexdigest())
        return
    # Keep unpublished dependency RPMs private to this build.
    with tempfile.TemporaryDirectory(prefix="rpmx-python-") as scratch:
        work = Path(scratch)
        local = work / "repo"
        local.mkdir()
        for settings, source, role in [
            (profile, profile_path, "build"),
            (test_profile, test_profile_path, "test"),
        ]:
            for repository in settings["repositories"]:
                for field in ("baseurl", "gpgkey"):
                    url = repository.get(field, "")
                    if url.startswith("file://"):
                        path = (source.parent / url[7:]).resolve()
                        # Each Podman root may relabel its file repository.
                        # Never relabel the shared toolchain seed in place.
                        if field == "baseurl" and repository["id"] == "eternal-toolchain":
                            private = work / role / "toolchain"
                            shutil.copytree(path, private)
                            path = private
                        # rpmx anchors file:// values as literal host paths.
                        repository[field] = f"file://{path}"
        profile_file = work / "profile.yaml"
        test_profile_file = work / "test-profile.yaml"
        # Include interpreter-qualified package names and declared capabilities.
        available = set()
        for name in order:
            for settings in (profile, test_profile):
                for repository in settings["repositories"]:
                    if repository["id"] != "python-local":
                        repository["exclude"] = sorted(set(repository.get("exclude", [])) | available)
            profile_file.write_text(yaml.safe_dump(profile, sort_keys=False))
            test_profile_file.write_text(yaml.safe_dump(test_profile, sort_keys=False))
            cache = root / ".work/python-deps" / args.arch / name / f"{hashes[name]}-{variant}"
            output = Path(args.output).resolve() if name == args.name else cache
            reports = (args.test_reports or Path(args.output) / "test-reports").resolve()
            reports = reports / "python" / args.name / args.arch / name / f"{hashes[name]}-{variant}"
            if name == args.name:
                reports = None  # Consumer evidence already lives in the public output.
            stamp = cache / ".complete"
            if name == args.name or not stamp.is_file():
                print(f"==> Python matrix {name}", flush=True)
                stamp.unlink(missing_ok=True)
                command = [
                    rpmx, "build", str(root / "packages" / name / "package.yaml"),
                    "--profile", str(profile_file), "--arch", args.arch,
                    "--output", str(output),
                ]
                if include_tests:
                    acceptance = [sys.executable, str(root / "scripts/accept-rpms.py"),
                                  str(root / "packages" / name / "package.yaml"),
                                  "--install-dir", str(output / args.arch),
                                  "--output", str(output / "acceptance" / args.arch),
                                  "--arch", args.arch, "--test-profile", str(test_profile_file)]
                    if include_optional_tests:
                        acceptance.append("--include-optional-tests")
                    if "--build-release" in build_args:
                        acceptance.extend(["--build-release", build_args[build_args.index("--build-release") + 1]])
                    build_with_evidence([*command, *build_args], output, reports, args.arch, root, acceptance)
                else:
                    # Disabled tests must not leave an older passing receipt.
                    for report in ("run-report.json", "run-report.xml"):
                        (output / report).unlink(missing_ok=True)
                    shutil.rmtree(output / "acceptance" / args.arch, ignore_errors=True)
                    subprocess.run([*command, *build_args], check=True, cwd=root)
                if name != args.name:
                    cache.mkdir(parents=True, exist_ok=True)
                    stamp.write_text("complete\n")
            elif include_tests:
                collect_test_evidence(output, reports, args.arch)
            rpms = [p for p in (output / args.arch).glob("*.rpm") if not p.name.endswith(".src.rpm")]
            if not rpms:
                raise SystemExit(f"{name} produced no binary RPMs")
            for rpm in rpms:
                shutil.copy2(rpm, local / rpm.name)
            for cell in plans[name]["cells"]:
                for binary in cell["outputs"]:
                    for capability in [binary["name"], *binary["provides"]]:
                        capability = capability.split()[0]
                        if re.fullmatch(r"python-(?:\d+\.\d+-)?[A-Za-z0-9._+-]+", capability):
                            available.add(capability)
            subprocess.run([rpmx, "repo", "--rpms", str(local), "--output", str(local)], check=True)
            for settings in (profile, test_profile):
                if not any(r["id"] == "python-local" for r in settings["repositories"]):
                    settings["repositories"].insert(0, {"id": "python-local", "baseurl": f"file://{local}"})


if __name__ == "__main__":
    main()
