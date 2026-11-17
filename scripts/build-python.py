#!/usr/bin/env python3
"""Prepare unpublished Python dependencies during the initial bootstrap.

Temporary normal-build integration. Retain new-interpreter bootstrap support
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
import tempfile

import yaml


def bootstrap_recipes(root):
    """Include every interpreter stream and every Python matrix recipe."""
    for recipe in sorted((root / "packages").glob("python-*/package.yaml")):
        data = yaml.safe_load(recipe.read_text())
        axes = data.get("matrix", {}).get("axes", {})
        if "python" in axes or re.fullmatch(r"python-\d+\.\d+", recipe.parent.name):
            yield recipe


def dependency_order(plans, name, *, tests=True, include_optional_tests=False):
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
            if tests:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--output", required=True)
    parser.add_argument("--arch", default=os.uname().machine)
    parser.add_argument("--profile", type=Path, help="Bootstrap profile for the new interpreter stream")
    args, build_args = parser.parse_known_args()
    include_optional_tests = "--include-optional-tests" in build_args
    if include_optional_tests and "--no-tests" in build_args:
        parser.error("--include-optional-tests cannot be combined with --no-tests")
    root = Path(__file__).resolve().parent.parent
    rpmx = os.environ.get("RPMX", "rpmx")

    def capture(*command):
        return subprocess.check_output(command, cwd=root, text=True)

    plans = {
        recipe.parent.name: json.loads(capture(rpmx, "plan", str(recipe), "--arch", args.arch, "--json"))["plan"]
        for recipe in bootstrap_recipes(root)
    }
    tests = "--no-tests" not in build_args
    order = dependency_order(plans, args.name, tests=tests,
                             include_optional_tests=include_optional_tests)
    hashes = dict(line.split() for line in capture(
        str(root / "scripts/package-hash.sh"), *order
    ).splitlines())
    hashes = bootstrap_hashes(order, hashes)
    profile_path = (args.profile or root / "profiles/bootstrap-python.profile.yaml").resolve()
    profile = yaml.safe_load(profile_path.read_text())
    variant = hashlib.sha256(json.dumps([
        build_args, str(profile_path), profile,
    ], sort_keys=True).encode()).hexdigest()[:12]
    # Each build gets a private mount. Podman's private SELinux labels cannot
    # safely share a repository directory between parallel build jobs.
    with tempfile.TemporaryDirectory(prefix="rpmx-python-") as scratch:
        work = Path(scratch)
        local = work / "repo"
        local.mkdir()
        for repository in profile["repositories"]:
            for field in ("baseurl", "gpgkey"):
                url = repository.get(field, "")
                if url.startswith("file://"):
                    path = (profile_path.parent / url[7:]).resolve()
                    repository[field] = path.as_uri()
                    # The compiler policy package also needs a private label.
                    if field == "baseurl" and repository["id"] == "eternal-toolchain":
                        shutil.copytree(path, work / "toolchain")
                        repository[field] = (work / "toolchain").as_uri()
        profile_file = work / "profile.yaml"
        # Include interpreter-qualified package names and declared capabilities.
        available = set()
        for name in order:
            for repository in profile["repositories"]:
                if repository["id"] in ("fedora", "updates"):
                    repository["exclude"] = sorted(set(repository.get("exclude", [])) | available)
            profile_file.write_text(yaml.safe_dump(profile, sort_keys=False))
            cache = root / ".work/python-deps" / args.arch / name / f"{hashes[name]}-{variant}"
            output = Path(args.output).resolve() if name == args.name else cache
            stamp = cache / ".complete"
            if name == args.name or not stamp.is_file():
                print(f"==> Python matrix {name}", flush=True)
                stamp.unlink(missing_ok=True)
                shutil.rmtree(output / "acceptance", ignore_errors=True)
                subprocess.run([
                    rpmx, "build", str(root / "packages" / name / "package.yaml"),
                    "--profile", str(profile_file), "--arch", args.arch,
                    "--output", str(output), *build_args,
                ], check=True, cwd=root)
                if tests:
                    acceptance = [
                        "python3", str(root / "scripts/accept-rpms.py"),
                        str(root / "packages" / name / "package.yaml"),
                        "--arch", args.arch, "--install-dir", str(output / args.arch),
                        "--test-profile", str(profile_file),
                        "--output", str(output / "acceptance" / args.arch),
                    ]
                    if include_optional_tests:
                        acceptance.append("--include-optional-tests")
                    if "--build-release" in build_args:
                        acceptance.extend(["--build-release", build_args[build_args.index("--build-release") + 1]])
                    subprocess.run(acceptance, check=True, cwd=root)
                if name != args.name:
                    cache.mkdir(parents=True, exist_ok=True)
                    stamp.write_text("complete\n")
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
            if not any(r["id"] == "python-local" for r in profile["repositories"]):
                profile["repositories"].insert(0, {"id": "python-local", "baseurl": local.as_uri()})


if __name__ == "__main__":
    main()
