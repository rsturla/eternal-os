#!/usr/bin/env python3
"""Plan dependency rebuilds and assemble fixed repository views for one main build."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
ARCHES = ('x86_64', 'aarch64')
RPMX = os.environ.get('RPMX', 'rpmx')


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, stdout=sys.stderr)


def capture(*args):
    return subprocess.check_output([str(arg) for arg in args], text=True)


def digest(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def capability(requirement):
    return requirement.split()[0]


def primary(repository):
    index = ET.parse(repository / 'repodata/repomd.xml')
    href = index.find("{*}data[@type='primary']/{*}location").get('href')
    path = repository / href
    data = path.read_bytes()
    return ET.fromstring(gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data)


def source_name(filename):
    if not filename or not filename.endswith('.src.rpm'):
        raise ValueError(f'missing source identity: {filename}')
    return filename[:-8].rsplit('-', 2)[0]


def open_url(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'eternal-package-builder/1'})
    return urllib.request.urlopen(request, timeout=120)


def baseline_packages(repository):
    records = []
    for package in primary(repository):
        version = package.find('{*}version')
        location = package.find('{*}location')
        href = location.get('href')
        base = location.get('{http://www.w3.org/XML/1998/namespace}base', '')
        checksum = package.find('{*}checksum')
        records.append({
            'name': package.findtext('{*}name'),
            'source': source_name(package.findtext('{*}format/{*}sourcerpm')),
            'provides': [entry.get('name') for entry in package.findall('{*}format/{*}provides/{*}entry')],
            'requires': [entry.get('name') for entry in package.findall('{*}format/{*}requires/{*}entry')],
            'url': urllib.parse.urljoin(base.rstrip('/') + '/', href) if base else href,
            'checksum': f'{checksum.get("type")}:{checksum.text}',
            **({'evr': [version.get('epoch', '0'), version.get('ver'), version.get('rel')]} if version is not None else {}),
        })
    return records


def catalog():
    hashes = dict(line.split() for line in capture(ROOT / 'scripts/package-hash.sh').splitlines())
    result = {}
    for recipe in sorted((ROOT / 'packages').glob('*/package.yaml')):
        targets = {}
        for arch in ARCHES:
            plan = json.loads(capture(RPMX, 'plan', recipe, '--arch', arch, '--json'))['plan']
            cells = plan['cells']
            outputs = [output for cell in cells for output in cell['outputs']]
            targets[arch] = {
                'sources': sorted({cell['package'] for cell in cells}),
                'provides': sorted({output['name'] for output in outputs} |
                                   {capability(value) for output in outputs for value in output['provides']}),
                'requires': sorted({capability(value) for cell in cells for value in cell['packages'] + cell['sysroot']} |
                                   {capability(value) for output in outputs for value in output['requires']} |
                                   {capability(value) for cell in cells for step in cell['pipeline']
                                    for value in step['needs_packages'] + step['needs_sysroot']}),
            }
        result[recipe.parent.name] = {'hash': hashes[recipe.parent.name], 'targets': targets}
    return result


def initialise(args):
    if args.state.exists():
        raise ValueError(f'transaction already exists: {args.state}')
    recipes = catalog()
    previous = {'hashes': {}}
    if args.published:
        try:
            with open_url(args.published.rstrip('/') + '/build-state.json') as response:
                previous = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        args.build_release = max(args.build_release, previous.get('build_release', 0) + 1)
        if previous.get('commit'):
            run('git', '-C', ROOT, 'merge-base', '--is-ancestor', previous['commit'], args.commit)
    selected = (sorted(name for name, data in recipes.items() if previous['hashes'].get(name) != data['hash'])
                if args.packages == 'changed' else json.loads(args.packages))
    if set(selected) - recipes.keys():
        raise ValueError('selected package has no recipe')
    baseline = {}
    for arch in ARCHES:
        repository = args.state.parent / 'baseline' / arch
        run('mergerepo_c', '--repo', args.base_url.rstrip('/') + '/rolling/' + arch,
            '--outputdir', repository, '--no-database', '--nogroups', '--noupdateinfo', '--compress-type=gz')
        baseline[arch] = baseline_packages(repository)
    policy = yaml.safe_load((ROOT / 'rebuild-policy.yaml').read_text()) or {}
    for provider, consumers in policy.items():
        if provider not in recipes or not isinstance(consumers, list) or set(consumers) - recipes.keys() - {'*'}:
            raise ValueError(f'invalid rebuild policy: {provider}')
    state = {'schema': 1, 'commit': args.commit, 'tree': capture('git', '-C', ROOT, 'rev-parse', 'HEAD^{tree}').strip(), 'catalog': recipes, 'baseline': baseline,
                       'published': previous, 'policy': policy, 'pending': selected, 'wave': 0,
                       'build_release': args.build_release, 'builds': {}, 'interfaces': {},
                       'baseline_interfaces': {}, 'requested': selected,
                       'reasons': {name: ['recipe inputs changed'] for name in selected}}
    state['pending'] = ready_packages(state, set(selected))
    write(args.state, state)
    emit(state)


def inspect_rpm(path):
    def query(format):
        return capture('rpm', '-qp', '--qf', format, path).splitlines()
    name, source, arch = query('%{NAME}\n%{SOURCERPM}\n%{ARCH}\n')
    evr = query('%{EPOCHNUM}\n%{VERSION}\n%{RELEASE}\n')
    provides = query('[%{PROVIDENAME}\n]')
    # A changed public library payload is a possible ABI change. Headers and
    # static libraries also invalidate consumers. This deliberately overbuilds
    # rather than claiming that matching SONAMEs prove ABI compatibility.
    sonames = {value.split('(')[0] for value in provides if '.so' in value}
    public = []
    payload = []
    for line in capture('rpm', '-qp', '--dump', path).splitlines():
        fields = shlex.split(line)
        filename, checksum = fields[0], fields[3]
        if not filename.startswith('/usr/share/sbom/'):
            payload.append([filename, checksum, fields[4], fields[-1]])
        if (Path(filename).name in sonames or
                any(Path(filename).name.startswith(soname + '.') for soname in sonames) or
                '/include/' in filename or filename.endswith('.a')):
            public.append([filename, checksum, fields[4], fields[-1]])
    interface = {'provides': sorted(value for value in provides if '.so' in value), 'files': sorted(public)}
    return {'name': name, 'source': source_name(source), 'arch': arch, 'evr': evr,
            'provides': provides, 'requires': query('[%{REQUIRENAME}\n]'),
            'interface': interface, 'payload': sorted(payload), 'sha512': digest(path, 'sha512'), 'sha256': digest(path), 'file': path.name}


def fingerprint(records, all_files=False):
    # Ignore RPM release counters, timestamps and package digests.
    public = ({record['name']: record['payload'] for record in records} if all_files else
              {record['name']: record['interface'] for record in records
               if record['interface']['provides'] or record['interface']['files']})
    return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def baseline_interface(state, package, arch, directory):
    records = []
    sources = state['catalog'][package]['targets'][arch]['sources']
    for entry in state['baseline'][arch]:
        if entry['source'] not in sources:
            continue
        algorithm, expected = entry['checksum'].split(':', 1)
        path = directory / (expected + '.rpm')
        if not path.exists():
            with open_url(entry['url']) as response, path.open('wb') as output:
                shutil.copyfileobj(response, output)
        if digest(path, algorithm) != expected:
            raise ValueError(f'published package checksum mismatch: {entry["url"]}')
        records.append(inspect_rpm(path))
    return fingerprint(records, package in state['policy'])


def dependencies(state, package, arch):
    target = state['catalog'][package]['targets'][arch]
    requires = set(target['requires'])
    for record in state['baseline'][arch]:
        if record['source'] in target['sources']:
            requires.update(record['requires'])
    build = state['builds'].get(package)
    if build:
        requires.update(build['targets'][arch]['requires'])
    result = set()
    for provider, data in state['catalog'].items():
        provides = set(data['targets'][arch]['provides'])
        for record in state['baseline'][arch]:
            if record['source'] in data['targets'][arch]['sources']:
                provides.update(record['provides'])
        candidate = state['builds'].get(provider)
        if candidate:
            provides.update(candidate['targets'][arch]['provides'])
        if requires & provides or package in state['policy'].get(provider, []) or '*' in state['policy'].get(provider, []):
            result.add(provider)
    if build:
        result.update(build['targets'][arch]['consumed'])
    return result - {package}


def next_packages(state):
    reasons = {name: {'recipe inputs changed'} for name in state.get('requested', []) if name not in state['builds']}
    for package in state['catalog']:
        for arch in ARCHES:
            for provider in dependencies(state, package, arch):
                current = state['interfaces'].get(provider, {}).get(arch)
                baseline = state['baseline_interfaces'].get(provider, {}).get(arch)
                if current is None or current == baseline:
                    continue
                built = state['builds'].get(package)
                consumed = built['view'].get(provider, {}).get(arch, baseline) if built else baseline
                if consumed != current:
                    reasons.setdefault(package, set()).add(f'{provider} changed public inputs on {arch}')
    return {package: sorted(values) for package, values in sorted(reasons.items())}


def ready_packages(state, waiting):
    """Build dependency SCCs before their consumers; use baseline for cycles."""
    edges = {package: set().union(*(dependencies(state, package, arch) for arch in ARCHES)) & waiting
             for package in waiting}
    # A package is ready if everything it waits for can reach it. Those edges
    # are a cycle, which must bootstrap together against the published set.
    def closure(start):
        seen, pending = set(), list(edges[start])
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(edges[current] - seen)
        return seen
    closures = {package: closure(package) for package in waiting}
    return sorted(package for package, providers in closures.items()
                  if all(package in closures[provider] for provider in providers))


def binary_directory(artifacts, package, arch, wave):
    return artifacts / f'binary-w{wave}-{package}-{arch}' / package / arch


def checked_binaries(directory, package, arch):
    record = json.loads((directory / 'source-manifest.json').read_text())
    if record['package'] != package or record['arch'] != arch or not record['binaries']:
        raise ValueError(f'invalid binary record: {directory}')
    if set(record['binaries']) != {path.name for path in directory.glob('*.rpm')}:
        raise ValueError(f'incomplete candidate: {directory}')
    for name, expected in record['binaries'].items():
        path = directory / name
        if Path(name).name != name or path.is_symlink() or digest(path) != expected:
            raise ValueError(f'candidate checksum mismatch: {path}')
    return record


def advance(args):
    state = json.loads(args.state.read_text())
    if not state['pending']:
        emit(state)
        return
    wave = state['wave']
    with tempfile.TemporaryDirectory(prefix='eternal-abi-') as temporary:
        for package in state['pending']:
            targets, view = {}, None
            for arch in ARCHES:
                directory = binary_directory(args.artifacts, package, arch, wave)
                record = checked_binaries(directory, package, arch)
                if record['view'] != state['interfaces']:
                    raise ValueError(f'{package} was built against another transaction view')
                view = record['view']
                rpms = [inspect_rpm(directory / name) for name in record['binaries']]
                if any(rpm['arch'] not in (arch, 'noarch') for rpm in rpms):
                    raise ValueError(f'foreign architecture in {directory}')
                targets[arch] = {'rpms': rpms, 'requires': sorted({value for rpm in rpms for value in rpm['requires']}),
                                 'provides': sorted({value for rpm in rpms for value in rpm['provides']}),
                                 'consumed': record['consumed']}
                state['baseline_interfaces'].setdefault(package, {})
                if arch not in state['baseline_interfaces'][package]:
                    state['baseline_interfaces'][package][arch] = baseline_interface(state, package, arch, Path(temporary))
                candidate_interface = fingerprint(rpms, package in state['policy'])
                targets[arch]['fingerprint'] = candidate_interface
            state['builds'][package] = {'wave': wave, 'view': view, 'targets': targets}
    # All siblings consumed the same old view. Publish their fingerprints into
    # state together, so iteration order cannot affect follow-on selection.
    for package in state['pending']:
        state['interfaces'][package] = {arch: state['builds'][package]['targets'][arch]['fingerprint'] for arch in ARCHES}
    state['reasons'] = next_packages(state)
    state['pending'] = ready_packages(state, set(state['reasons']))
    state['wave'] += 1
    if args.final and state['pending']:
        raise ValueError(f'rebuild closure did not settle: {state["reasons"]}')
    write(args.state, state)
    emit(state)


def emit(state):
    print(json.dumps({'packages': state['pending'], 'wave': state['wave'],
                      'complete': not state['pending'], 'built': sorted(state['builds'])}, separators=(',', ':')))


def view(args):
    state = json.loads(args.state.read_text())
    spec = importlib.util.spec_from_file_location('filter_rolling', ROOT / 'scripts/filter-rolling.py')
    filtering = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(filtering)
    for arch in ARCHES:
        destination = args.output / arch
        if not state['builds']:
            shutil.copytree(args.state.parent / 'baseline' / arch, destination)
            continue
        with tempfile.TemporaryDirectory(prefix='eternal-view-') as temporary:
            scratch = Path(temporary)
            pool = scratch / 'pool'
            pool.mkdir()
            replaced = set()
            for package, build in state['builds'].items():
                directory = binary_directory(args.artifacts, package, arch, build['wave'])
                record = checked_binaries(directory, package, arch)
                for rpm in build['targets'][arch]['rpms']:
                    source = directory / rpm['file']
                    if record['binaries'].get(rpm['file']) != rpm['sha256'] or (pool / source.name).exists():
                        raise ValueError(f'duplicate or changed candidate: {source}')
                    shutil.copy2(source, pool / source.name)
                    replaced.add(rpm['source'])
            run(RPMX, 'repo', '--rpms', pool, '--output', scratch / 'new')
            filtering.filter_repository(args.state.parent / 'baseline' / arch, scratch / 'old', replaced)
            run('mergerepo_c', '--all', '--repo', scratch / 'old', '--repo', scratch / 'new',
                '--outputdir', destination, '--no-database', '--nogroups', '--noupdateinfo', '--compress-type=gz')
            metadata = primary(destination)
            for entry in metadata:
                location = entry.find('{*}location')
                filename = Path(location.get('href')).name
                if filename in {path.name for path in pool.iterdir()}:
                    location.set('href', filename)
                    location.attrib.pop('{http://www.w3.org/XML/1998/namespace}base', None)
            ET.register_namespace('', 'http://linux.duke.edu/metadata/common')
            ET.register_namespace('rpm', 'http://linux.duke.edu/metadata/rpm')
            xml = scratch / 'primary.xml'
            ET.ElementTree(metadata).write(xml, encoding='utf-8', xml_declaration=True)
            run('modifyrepo_c', '--mdtype', 'primary', '--compress', '--compress-type=gz',
                '--unique-md-filenames', xml, destination / 'repodata')
            for path in pool.iterdir():
                shutil.copy2(path, destination / path.name)


def seal(args):
    state = json.loads(args.state.read_text())
    if state['pending']:
        raise ValueError('cannot accept an unfinished rebuild closure')
    view(args)
    state['repositories'] = {arch: digest(args.output / arch / 'repodata/repomd.xml') for arch in ARCHES}
    write(args.state, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest='operation', required=True)
    for name, function in [('init', initialise), ('advance', advance), ('view', view), ('seal', seal)]:
        command = operations.add_parser(name)
        command.add_argument('--state', type=Path, required=True)
        command.set_defaults(function=function)
        if name == 'init':
            command.add_argument('--packages', default='changed', help='changed or a JSON array')
            command.add_argument('--base-url', default='https://packages.eternal.sturla.tech')
            command.add_argument('--published', help='Read published recipe hashes from this URL')
            command.add_argument('--commit', default=capture('git', '-C', ROOT, 'rev-parse', 'HEAD').strip())
            command.add_argument('--build-release', type=int, required=True)
        else:
            command.add_argument('--artifacts', type=Path, required=True)
            if name == 'advance':
                command.add_argument('--final', action='store_true')
            else:
                command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
