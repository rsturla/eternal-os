#!/usr/bin/env python3
"""Overlay candidate binary RPMs on a production profile for isolated tests."""

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

CANDIDATE_REPOSITORY = "rpmx-test-candidates"


def file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def rpm_metadata(path):
    fields = ["NAME", "EPOCHNUM", "VERSION", "RELEASE", "ARCH", "SOURCEPACKAGE"]
    query = "\n".join(f"%{{{field}}}" for field in fields) + "\n"
    result = subprocess.run(
        ["rpm", "-qp", "--queryformat", query, "--", str(path)],
        check=True, capture_output=True, text=True,
    )
    values = result.stdout.splitlines()
    if len(values) != len(fields):
        raise ValueError(f"invalid RPM metadata in {path.name}")
    metadata = dict(zip((field.lower() for field in fields), values))
    if metadata.pop("sourcepackage") == "1" or metadata["arch"] in ("src", "nosrc"):
        raise ValueError(f"source RPM is not a candidate binary: {path.name}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._-]*", metadata["name"]):
        raise ValueError(f"invalid candidate package name in {path.name}")
    return metadata


def relocate_profile(profile, source, arch, names, repository):
    """Keep the base policy and anchor local paths before moving its profile."""
    result = copy.deepcopy(profile)
    if arch not in result.get("archs", []):
        raise ValueError(f"base profile does not support architecture {arch}")
    result["archs"] = [arch]
    repositories = result.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("base profile must declare repositories")
    for entry in repositories:
        if entry["id"] == CANDIDATE_REPOSITORY:
            raise ValueError("base profile already contains a candidate repository")
        for field in ("baseurl", "gpgkey"):
            value = entry.get(field)
            if isinstance(value, str) and value.startswith("file://"):
                # rpmx treats file:// values as literal filesystem paths.
                path = Path(value[7:])
                if not path.is_absolute():
                    entry[field] = "file://" + str((source.parent / path).resolve())
        excluded = entry.get("exclude", [])
        if not isinstance(excluded, list) or any(not isinstance(name, str) for name in excluded):
            raise ValueError(f"repository {entry['id']} has an invalid exclude list")
        entry["exclude"] = sorted(set(excluded) | names)
    repositories.insert(0, {
        "id": CANDIDATE_REPOSITORY,
        "baseurl": "file://" + str(repository),
    })
    return result


def validate_repository(repository, inputs):
    """Never reuse a damaged snapshot under its immutable repository URL."""
    recorded = json.loads((repository / "candidate-inputs.json").read_text())
    if recorded["inputs"] != inputs:
        raise ValueError(f"candidate repository inputs changed: {repository}")
    present = {str(path.relative_to(repository)) for path in repository.rglob("*") if path.is_file()}
    if present != set(recorded["files"]) | {"candidate-inputs.json"}:
        raise ValueError(f"candidate repository file set changed: {repository}")
    for filename, expected in recorded["files"].items():
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid candidate repository manifest: {repository}")
        path = repository / relative
        if path.is_symlink() or not path.is_file() or file_digest(path) != expected:
            raise ValueError(f"candidate repository is damaged: {path}")
    if "repodata/repomd.xml" not in recorded["files"]:
        raise ValueError(f"candidate repository has no metadata: {repository}")


def prepare(profile, rpms, arch, output, rpmx):
    profile, rpms, output = profile.resolve(), rpms.resolve(), output.resolve()
    if output == profile:
        raise ValueError("output must not replace the base profile")
    if output.is_relative_to(rpms):
        raise ValueError("output profile must be outside the candidate RPM directory")
    if arch in ("all", "noarch", "src", "nosrc"):
        raise ValueError("choose one concrete target architecture")
    data = yaml.safe_load(profile.read_text())
    if not isinstance(data, dict) or data.get("document") != "rpmx-profile":
        raise ValueError("base file must be an rpmx profile")
    if not rpms.is_dir():
        raise ValueError(f"candidate RPM directory does not exist: {rpms}")
    candidates = sorted(rpms.rglob("*.rpm"))
    if not candidates:
        raise ValueError(f"no candidate RPMs found in {rpms}")
    output.parent.mkdir(parents=True, exist_ok=True)
    repository_parent = output.with_suffix(".repo")
    repository_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=repository_parent) as temporary:
        work = Path(temporary)
        snapshots = work / "rpms"
        snapshots.mkdir()
        outputs = {}
        for index, candidate in enumerate(candidates):
            # Query the copied bytes, not a mutable input or symlink target.
            snapshot = snapshots / f"{index}.rpm"
            shutil.copyfile(candidate, snapshot)
            try:
                metadata = rpm_metadata(snapshot)
            except (ValueError, subprocess.CalledProcessError) as error:
                detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
                raise ValueError(f"invalid candidate RPM {candidate}: {detail}") from error
            if metadata["arch"] not in (arch, "noarch"):
                raise ValueError(f"candidate {candidate} has architecture {metadata['arch']}, expected {arch} or noarch")
            metadata["sha256"] = file_digest(snapshot)
            name = metadata["name"]
            if name in outputs:
                if metadata != outputs[name]:
                    raise ValueError(f"conflicting candidate versions or payloads for {name}")
                snapshot.unlink()
                continue
            outputs[name] = metadata
            snapshot.rename(snapshots / (metadata["sha256"] + ".rpm"))
        inputs = {"arch": arch, "rpms": sorted(outputs.values(), key=lambda item: item["name"])}
        identity = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        repository = repository_parent / identity
        result = relocate_profile(data, profile, arch, set(outputs), repository)
        if repository.exists():
            validate_repository(repository, inputs)
        else:
            generated = work / "repository"
            subprocess.run(
                [rpmx, "repo", "--rpms", str(snapshots), "--output", str(generated)],
                check=True, stdout=sys.stderr,
            )
            if not (generated / "repodata/repomd.xml").is_file():
                raise ValueError("rpmx repo did not produce repository metadata")
            files = {str(path.relative_to(generated)): file_digest(path)
                     for path in sorted(generated.rglob("*")) if path.is_file()}
            (generated / "candidate-inputs.json").write_text(json.dumps({"inputs": inputs, "files": files}, indent=2) + "\n")
            # The final URL is published only after the repository is complete.
            try:
                generated.rename(repository)
            except OSError:
                # Another invocation may have published the same snapshot.
                if not repository.is_dir():
                    raise
                validate_repository(repository, inputs)
        with tempfile.NamedTemporaryFile(mode="w", prefix=".profile-", dir=output.parent, delete=False) as pending:
            pending_path = Path(pending.name)
            try:
                yaml.safe_dump(result, pending, sort_keys=False)
                pending.close()
                pending_path.replace(output)
            finally:
                pending_path.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--rpms", required=True, type=Path)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        prepare(args.profile, args.rpms, args.arch, args.output, os.environ.get("RPMX", "rpmx"))
    except (OSError, ValueError, KeyError, yaml.YAMLError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"cannot prepare candidate test profile: {error}\n")


if __name__ == "__main__":
    main()
