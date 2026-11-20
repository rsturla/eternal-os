#!/usr/bin/env python3
"""Resolve recipe inputs against the same profile used by source preparation."""

import json
from pathlib import Path
import subprocess

import yaml


def snapshot_profile(recipe, repository, destination):
    document = yaml.safe_load(recipe.read_text())
    path = (recipe.parent / document['build']['root']['profile']).resolve()
    profile = yaml.safe_load(path.read_text())
    for entry in profile['repositories']:
        if entry.get('id') == 'eternal':
            entry['baseurl'] = repository.rstrip('/') + '/$basearch'
    destination.write_text(yaml.safe_dump(profile, sort_keys=False))
    return destination


def resolve(rpmx, recipe, arch, repository, cache, output, build_release):
    """Return an unsatisfied-input diagnostic; all other failures are fatal."""
    output.mkdir(parents=True)
    profile = snapshot_profile(recipe, repository, output / 'profile.yaml')
    result = subprocess.run(list(map(str, [rpmx, 'inputs', recipe, '--arch', arch,
        '--profile', profile, '--cache', cache, '--output', output,
        '--build-release', build_release, '--json'])), capture_output=True, text=True)
    (output / 'stdout.log').write_text(result.stdout)
    (output / 'stderr.log').write_text(result.stderr)
    # Use the durable application report, not terminal text or exit status alone.
    report = json.loads((output / 'run-report.json').read_text())
    if result.returncode == 0 and report['outcome'] == 'passed':
        return None
    diagnostic = report.get('primary') or {}
    if (diagnostic.get('code') == 'RPMX-ROOT-007'
            and 'Failed to resolve the transaction' in diagnostic.get('message', '')):
        return diagnostic
    raise RuntimeError(f'input resolution failed for {recipe.parent.name}/{arch}: '
                       f'{diagnostic}\n{result.stderr}')
