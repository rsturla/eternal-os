#!/usr/bin/env python3
"""Export canonical build outputs or assemble an architecture's acceptance pool."""

import argparse
import json
from pathlib import Path
import shutil


def canonical(path, arch):
    return (path.is_file() and not path.is_symlink()
            and path.name.endswith((f'.{arch}.rpm', '.noarch.rpm'))
            and not path.name.endswith('.src.rpm'))


def export(source, destination, arch):
    policy = source / 'build-policy.json'
    if policy.is_symlink() or not policy.is_file():
        raise ValueError(f'missing build policy: {policy}')
    document = json.loads(policy.read_text())
    if set(document) != {'build_release'}:
        raise ValueError(f'invalid build policy: {policy}')
    rpms = [path for path in source.glob('*.rpm') if canonical(path, arch)]
    if not rpms:
        raise ValueError(f'no canonical {arch} RPMs in {source}')
    destination.mkdir(parents=True, exist_ok=False)
    for path in [*rpms, policy]:
        shutil.copy2(path, destination / path.name)


def assemble(source, destination, arch):
    # Each downloaded artifact contains only its canonical binaries and policy.
    # Validate everything before creating the shared pool; never overwrite bytes.
    rpms = {}
    for member in sorted(source.iterdir()):
        if member.is_symlink() or not member.is_dir():
            raise ValueError(f'invalid candidate artifact: {member}')
        policy = member / 'build-policy.json'
        if policy.is_symlink() or not policy.is_file():
            raise ValueError(f'missing candidate policy: {member}')
        binaries = []
        for path in member.iterdir():
            if path.name == 'build-policy.json':
                continue
            if not canonical(path, arch):
                raise ValueError(f'noncanonical candidate: {path}')
            if path.name in rpms:
                raise ValueError(f'duplicate candidate filename: {path.name}')
            rpms[path.name] = path
            binaries.append(path)
        if not binaries:
            raise ValueError(f'empty candidate artifact: {member}')
    if not rpms:
        raise ValueError('empty candidate pool')
    destination.mkdir(parents=True, exist_ok=False)
    for name, path in rpms.items():
        shutil.copy2(path, destination / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['export', 'assemble'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arch', required=True, choices=['x86_64', 'aarch64'])
    args = parser.parse_args()
    try:
        operation = export if args.operation == 'export' else assemble
        operation(args.source, args.output, args.arch)
    except (OSError, ValueError) as error:
        parser.exit(1, f'candidate pool: {error}\n')


if __name__ == '__main__':
    main()
