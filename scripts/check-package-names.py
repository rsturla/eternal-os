#!/usr/bin/env python3
"""Check Eternal package identities and Python stream names."""

from pathlib import Path
import re
import sys

import yaml


def check(root):
    recipes = sorted((root / "packages").glob("*/package.yaml"))
    streams = sorted(
        path.parent.name.removeprefix("python-")
        for path in recipes
        if re.fullmatch(r"python-\d+\.\d+", path.parent.name)
    )
    defaults = yaml.safe_load((root / "rpmx-defaults.yaml").read_text())
    default = defaults.get("metadata", {}).get("python", {}).get("default-stream")
    errors = []
    if streams and default not in streams:
        errors.append("rpmx-defaults.yaml: metadata.python.default-stream must name a supported stream")
    for path in recipes:
        data = yaml.safe_load(path.read_text())
        name = data["package"]["name"]
        if name != path.parent.name:
            errors.append(f"{path}: source name must match its directory")
        if re.fullmatch(r"python-\d+\.\d+", name):
            version = name.removeprefix("python-")
            selector = next((output for output in data.get("outputs", [])
                             if output["name"] == name + "-default"), None)
            expected = "python3 = ${package.version}-${package.release}" if version == default else "python3 = 0"
            provides = selector.get("dependencies", {}).get("provides", []) if selector else []
            if expected not in provides:
                errors.append(f"{path}: default command output must provide {expected}")
        axes = data.get("matrix", {}).get("axes", {})
        if "python" not in axes:
            continue
        if not re.fullmatch(r"python-[a-z0-9]+(?:-[a-z0-9]+)*", name):
            errors.append(f"{path}: Python source name must be python-<normalized-project>")
            continue
        module = name.removeprefix("python-")
        expected = "python-${matrix.python.version}-" + module
        outputs = data.get("outputs", [])
        if not outputs or outputs[0]["name"] != expected:
            errors.append(f"{path}: main output must be {expected}")
        for output in outputs[1:]:
            if not output["name"].startswith(expected + "-"):
                errors.append(f"{path}: subpackage must extend the versioned module name")
        cells = axes["python"]
        versions = [str(cell.get("version", "")) for cell in cells]
        if sorted(versions) != streams:
            errors.append(f"{path}: Python matrix must cover supported streams {streams}")
        for cell in cells:
            version = str(cell.get("version", ""))
            capability = "python" if version == default else "python-" + version
            if cell.get("capability") != capability:
                errors.append(f"{path}: Python {version} capability must be {capability}")
        provides = outputs[0].get("dependencies", {}).get("provides", []) if outputs else []
        alias = "${matrix.python.capability}-" + module
        if not any(value.split()[0] == alias for value in provides):
            errors.append(f"{path}: default capability must be {alias}")
    return errors


if __name__ == "__main__":
    failures = check(Path(__file__).resolve().parent.parent)
    for failure in failures:
        print(failure, file=sys.stderr)
    if failures:
        raise SystemExit(1)
    print("package naming: ok")
