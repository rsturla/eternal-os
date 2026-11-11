#!/usr/bin/env python3
"""Build selected compiler candidates, then accept the complete cohort before use."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED = "openssf-compiler-options"
COMPILERS = tuple(f"gcc-{version}" for version in range(13, 17))
RPMX = os.environ.get("RPMX", "rpmx")
spec = importlib.util.spec_from_file_location("candidate_profile", ROOT / "scripts/prepare-test-profile.py")
candidate_profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate_profile)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checked(command, log=None):
    print("==> " + " ".join(map(str, command)), flush=True)
    if log is None:
        subprocess.run(command, check=True)
        return
    with log.open("w") as evidence:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end="", flush=True)
            evidence.write(line)
        status = process.wait()
    if status:
        raise subprocess.CalledProcessError(status, command)


def source_identity(name, arch, build_release):
    package_hash = subprocess.check_output([str(ROOT / "scripts/package-hash.sh"), name], text=True).split()[1]
    binary = Path(shutil.which(RPMX) or RPMX).resolve(strict=True)
    return {"package": name, "arch": arch, "build_release": build_release,
            "package_hash": package_hash, "rpmx_revision": (ROOT / ".rpmx-revision").read_text().strip(),
            "rpmx_binary": digest(binary)}


def plan(name, arch, build_release):
    command = [RPMX, "plan", str(ROOT / "packages" / name / "package.yaml"), "--arch", arch, "--json"]
    if build_release:
        command.extend(["--build-release", build_release])
    return json.loads(subprocess.check_output(command, text=True))["plan"]


def products(directory, name, arch, build_release, original_build=None):
    planned = plan(name, arch, build_release)
    expected = {output["name"]: {"name": output["name"], "epochnum": "0",
                "version": cell["version"], "release": cell["release"], "arch": output.get("arch") or arch}
                for cell in planned["cells"] for output in cell["outputs"]}
    report = json.loads((directory / "build/run-report.json").read_text())
    original_build = Path(original_build) if original_build else directory / "build"
    def artifact(path):
        relative = Path(path).relative_to(original_build)
        if ".." in relative.parts:
            raise ValueError(f"build artifact escapes producer: {path}")
        return directory / "build" / relative
    binary_paths = [artifact(path) for path in report["artifacts"]["rpms"]]
    source_paths = [artifact(path) for path in report["artifacts"]["srpms"]]
    if len(set(binary_paths + source_paths)) != len(binary_paths + source_paths):
        raise ValueError("duplicate reported build artifact")
    if set((directory / "build" / arch).rglob("*.rpm")) != set(binary_paths + source_paths):
        raise ValueError(f"unreported or missing RPM artifacts for {name}")
    binaries = {}
    for path in binary_paths:
        if path.parent != directory / "build" / arch:
            raise ValueError(f"unexpected nested candidate RPM: {path}")
        metadata = candidate_profile.rpm_metadata(path)
        if metadata != expected.get(metadata["name"]):
            raise ValueError(f"candidate does not match the current plan: {path}: {metadata}")
        if metadata["name"] in binaries:
            raise ValueError(f"duplicate candidate output: {metadata['name']}")
        binaries[metadata["name"]] = path
    for path in source_paths:
        source = subprocess.check_output(["rpm", "-qp", "--queryformat", "%{SOURCEPACKAGE}", "--", str(path)], text=True).strip()
        if source != "1":
            raise ValueError(f"reported source artifact is not a source RPM: {path}")
    if set(binaries) != set(expected):
        raise ValueError(f"incomplete outputs for {name}: expected {sorted(expected)}, found {sorted(binaries)}")
    count = sum(len(cell["build_tests"]) for cell in planned["cells"])
    if not (report.get("document") == "rpmx-run-report" and report.get("version") == 1
            and report.get("outcome") == "passed" and report.get("build_tests_requested") is True
            and len(report.get("build_tests", [])) == count
            and all(case.get("status") == "passed" for case in report["build_tests"])):
        raise ValueError(f"incomplete source-test evidence: {directory / 'build/run-report.json'}")
    return binaries


def files(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"producer input contains a symlink: {path}")
        if path.is_file() and path != directory / "producer.json":
            result[str(path.relative_to(directory))] = digest(path)
    return result


def verify(directory, name, arch, build_release):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"producer must be a real directory: {directory}")
    record = json.loads((directory / "producer.json").read_text())
    if record.get("document") != "eternal-compiler-producer" or record.get("version") != 1:
        raise ValueError(f"invalid producer manifest: {directory}")
    if record.get("source") != source_identity(name, arch, build_release):
        raise ValueError(f"producer source, target or rpmx identity differs: {directory}")
    if record.get("files") != files(directory):
        raise ValueError(f"producer files changed or are incomplete: {directory}")
    return products(directory, name, arch, build_release, record["build_directory"])


def produce(args, name):
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    identity = source_identity(name, args.arch, args.build_release)
    profile = None
    seed_identity = None
    if name != SEED:
        seed_input = destination / "seed-input"
        shutil.copytree(args.seed.resolve(), seed_input, symlinks=True)
        seed = verify(seed_input, SEED, args.arch, args.build_release)
        seed_identity = digest(seed_input / "producer.json")
        repository = destination / "seed-repository"
        seed_rpms = destination / "seed-rpms"
        seed_rpms.mkdir()
        for path in seed.values():
            shutil.copyfile(path, seed_rpms / path.name)
        checked([RPMX, "repo", "--rpms", str(seed_rpms), "--output", str(repository)])
        base = ROOT / "profiles/bootstrap.profile.yaml"
        data = yaml.safe_load(base.read_text())
        found = False
        for entry in data["repositories"]:
            for field in ("baseurl", "gpgkey"):
                value = entry.get(field)
                if isinstance(value, str) and value.startswith("file://"):
                    entry[field] = "file://" + str((base.parent / value[7:]).resolve())
            if entry["id"] == "eternal-toolchain":
                entry["baseurl"] = "file://" + str(repository)
                found = True
            else:
                entry["exclude"] = sorted(set(entry.get("exclude", [])) | {SEED})
        if not found:
            raise ValueError("bootstrap profile has no eternal-toolchain seed repository")
        profile = destination / "build-profile.yaml"
        profile.write_text(yaml.safe_dump(data, sort_keys=False))
    command = [RPMX, "build", str(ROOT / "packages" / name / "package.yaml"),
               "--arch", args.arch, "--output", str(destination / "build")]
    if profile:
        command.extend(["--profile", str(profile)])
    for option in ("build_release", "signing_key", "jobs"):
        value = getattr(args, option)
        if value:
            command.extend(["--" + option.replace("_", "-"), str(value)])
    if args.locked:
        command.append("--locked")
    checked(command, destination / "build.log")
    products(destination, name, args.arch, args.build_release)
    if source_identity(name, args.arch, args.build_release) != identity:
        raise ValueError("source, profile or rpmx identity changed during the build")
    record = {"document": "eternal-compiler-producer", "version": 1,
              "source": identity,
              "build_directory": str(destination / "build"),
              "commit": os.environ.get("GITHUB_SHA"), "seed_manifest": seed_identity,
              "files": files(destination)}
    (destination / "producer.json").write_text(json.dumps(record, indent=2) + "\n")


def accept(args):
    if len(set(args.package)) != len(args.package):
        raise ValueError("duplicate cohort member")
    compilers = [name for name in args.package if name in COMPILERS]
    if not compilers:
        raise ValueError("compiler acceptance requires at least one selected GCC stream")
    names = [SEED, *compilers]
    inputs = args.inputs.resolve()
    # Copy into private storage before validation. Acceptance must consume the
    # exact validated bytes, even if a caller changes the downloaded artifact.
    with tempfile.TemporaryDirectory(prefix="compiler-cohort-") as temporary:
        work = Path(temporary)
        shutil.copytree(inputs, work / "inputs", symlinks=True)
        inputs = work / "inputs"
        if {path.name for path in inputs.iterdir()} != set(names):
            raise ValueError(f"producer input set must be exactly {names}")
        binaries = {name: verify(inputs / name, name, args.arch, args.build_release) for name in names}
        seed_identity = digest(inputs / SEED / "producer.json")
        for name in compilers:
            record = json.loads((inputs / name / "producer.json").read_text())
            if record["seed_manifest"] != seed_identity:
                raise ValueError(f"compiler used a different seed: {name}")
        pool = work / "rpms"
        pool.mkdir()
        for outputs in binaries.values():
            for path in outputs.values():
                if (pool / path.name).exists():
                    raise ValueError(f"duplicate candidate filename: {path.name}")
                shutil.copyfile(path, pool / path.name)
        reports = args.output.resolve() / "test-reports/compiler-cohort" / args.arch
        reports.mkdir(parents=True, exist_ok=False)
        profile = reports / "profile.yaml"
        candidate_profile.prepare(ROOT / "profiles/eternal.profile.yaml", pool, args.arch, profile, RPMX)
        for name in names:
            command = [sys.executable, str(ROOT / "scripts/accept-rpms.py"),
                       str(ROOT / "packages" / name / "package.yaml"), "--arch", args.arch,
                       "--install-dir", str(inputs / name / "build" / args.arch),
                       "--output", str(reports / name), "--test-profile", str(profile)]
            if args.build_release:
                command.extend(["--build-release", args.build_release])
            checked(command)
        # No success stamp or candidate destination exists before the entire
        # acceptance gate passes. Keep input artifacts under producer-* names.
        args.output.mkdir(parents=True, exist_ok=True)
        args.rpms.parent.mkdir(parents=True, exist_ok=True)
        args.rpms.mkdir(exist_ok=True)
        if any(args.rpms.iterdir()):
            raise ValueError("compiler candidate destination must be empty")
        for name in args.package:
            if (args.output / name).exists():
                raise ValueError(f"refusing to overwrite earlier package outputs: {args.output / name}")
        with tempfile.TemporaryDirectory(prefix=".compiler-promotion-", dir=args.rpms.parent) as pending:
            staged = Path(pending) / "rpms"
            staged.mkdir()
            for name in args.package:
                for path in binaries[name].values():
                    shutil.copyfile(path, staged / path.name)
            for name in args.package:
                source = inputs / name / "build"
                destination = args.output / name
                # Evidence can contain deliberately corrupt or unsigned RPMs.
                # Only report-declared production artifacts enter normal output.
                shutil.copytree(source, destination, ignore=shutil.ignore_patterns("*.rpm"))
                record = json.loads((inputs / name / "producer.json").read_text())
                report = json.loads((source / "run-report.json").read_text())
                for path in report["artifacts"]["rpms"] + report["artifacts"]["srpms"]:
                    relative = Path(path).relative_to(record["build_directory"])
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / relative, target)
            # Publish the consumer pool last, with an atomic directory rename.
            # Its contents are only the validated top-level production RPMs.
            staged.replace(args.rpms)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("produce-seed", "produce", "accept"):
        child = commands.add_parser(command)
        child.add_argument("--arch", required=True, choices=("x86_64", "aarch64"))
        child.add_argument("--output", required=True, type=Path)
        child.add_argument("--build-release")
        if command == "accept":
            child.add_argument("--package", required=True, choices=(SEED, *COMPILERS), action="append")
            child.add_argument("--inputs", required=True, type=Path)
            child.add_argument("--rpms", required=True, type=Path)
        else:
            child.add_argument("--signing-key", type=Path)
            child.add_argument("--jobs")
            child.add_argument("--locked", action="store_true")
            if command == "produce":
                child.add_argument("--package", required=True, choices=COMPILERS)
                child.add_argument("--seed", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "accept":
            accept(args)
        else:
            produce(args, SEED if args.command == "produce-seed" else args.package)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"compiler cohort {args.command} failed: {error}\n")


if __name__ == "__main__":
    main()
