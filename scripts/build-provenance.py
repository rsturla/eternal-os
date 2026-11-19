"""Evaluate durable RPM build receipts against portable repair requirements."""

import json
import os
import re
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def load():
    import yaml
    path = ROOT / 'rebuild-requirements.yaml'
    document = yaml.safe_load(path.read_text())
    if not isinstance(document, dict) or document.get('schema') != 1 or set(document) != {'schema', 'requirements'}:
        raise ValueError('invalid rebuild requirement document')
    requirements = document['requirements']
    if not isinstance(requirements, list):
        raise ValueError('rebuild requirements must be a list')
    for item in requirements:
        if (not isinstance(item, dict) or set(item) - {'capability', 'minimum', 'minimum_evr', 'arches'}
                or not isinstance(item.get('capability'), str)
                or not re.fullmatch(r'rpmx\([A-Za-z0-9][A-Za-z0-9:+._-]*\)', item['capability'])
                or not isinstance(item.get('minimum'), str) or not item['minimum']
                or ('minimum_evr' in item and (not isinstance(item['minimum_evr'], str) or not item['minimum_evr']))
                or ('arches' in item and (not isinstance(item['arches'], list) or not item['arches']
                    or set(item['arches']) - {'x86_64', 'aarch64'}))):
            raise ValueError(f'invalid rebuild requirement: {item}')
    return requirements


def compare(left, right):
    # Keep RPM epoch, tilde and caret ordering, without macro/code injection.
    def evr(value):
        epoch, version = value.split(':', 1) if ':' in value else ('0', value)
        version, release = version.rsplit('-', 1) if '-' in version else (version, '')
        return epoch, version, release
    def literal(value):
        return '"' + ''.join(f'\\{byte:03d}' for byte in value.encode()) + '"'
    for first, second in zip(evr(left), evr(right), strict=True):
        if first == second:
            continue
        if not first or not second:
            return 1 if first else -1
        result = int(subprocess.check_output(['rpm', '--eval', '%{lua:print(rpm.vercmp('
                     + literal(first) + ',' + literal(second) + '))}'], text=True))
        if result:
            return result
    return 0


def read(path):
    return json.loads(subprocess.check_output([os.environ.get('RPMX', 'rpmx'), 'provenance', str(path)], text=True))


def failures(receipt, requirements, arch):
    applicable = [item for item in requirements if arch in item.get('arches', ['x86_64', 'aarch64'])]
    if not applicable:
        return []
    if receipt is None or receipt.get('schema') != 1 or not receipt.get('roots_complete'):
        return ['missing complete build-root provenance']
    reasons = []
    for requirement in applicable:
        capability = requirement['capability']
        for provider in receipt['inputs']:
            if capability not in provider['provides']:
                continue
            coverage = [item for item in receipt['coverage'] if item['root'] == provider['root']
                        and item['checksum'] == provider['checksum']]
            if (capability.startswith('rpmx(component:') and any(item['complete']
                    and capability not in item['used'] for item in coverage)):
                continue
            value = provider['provides'][capability]
            if (not value or compare(value, requirement['minimum']) < 0
                    or ('minimum_evr' in requirement and compare(provider['evr'], requirement['minimum_evr']) < 0)):
                reasons.append(f'{capability} from {provider["name"]} {provider["evr"]} is below the repair requirement')
    return reasons


def verify(path, requirements, arch):
    reasons = failures(read(path), requirements, arch)
    if reasons:
        raise ValueError(f'{path}: {"; ".join(reasons)}')
