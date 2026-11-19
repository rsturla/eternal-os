#!/usr/bin/env python3
"""Select the final transaction and stage its tested artifacts for publication."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(args):
    states = [(int(path.parent.name.removeprefix('transaction-w')), path)
              for path in args.states.glob('transaction-w*/state.json')]
    if not states:
        raise ValueError('no transaction state was uploaded')
    _, latest = max(states)
    state = json.loads(latest.read_text())
    if state['pending']:
        raise ValueError(f'unfinished rebuild closure: {state["pending"]}')
    shutil.copytree(latest.parent, args.output)
    matrix = [{'package': package, 'arch': arch, 'wave': build['wave'],
               'runner': 'ubuntu-26.04-arm' if arch == 'aarch64' else 'ubuntu-26.04'}
              for package, build in sorted(state['builds'].items())
              for arch in state.get('arches', ('x86_64', 'aarch64'))]
    print(json.dumps({'matrix': matrix, 'packages': sorted(state['builds'])}, separators=(',', ':')))


def stage(args):
    artifacts = load('package-artifacts')
    state = json.loads(args.state.read_text())
    if state['pending'] or not state.get('repositories'):
        raise ValueError('transaction has not reached acceptance')
    for package, build in state['builds'].items():
        bundle = args.artifacts / f'source-w{build["wave"]}-{package}'
        for arch in state.get('arches', ('x86_64', 'aarch64')):
            source = args.artifacts / f'accepted-{package}-{arch}' / package / arch
            record = json.loads((source / 'source-manifest.json').read_text())
            if record.get('acceptance_repository') != state['repositories'][arch]:
                raise ValueError('acceptance used another repository generation')
            destination = args.output / package / arch
            destination.mkdir(parents=True)
            for name in [*record['binaries'], 'source-manifest.json']:
                if Path(name).name != name:
                    raise ValueError('invalid accepted filename')
                shutil.copy2(source / name, destination / name)
        artifacts.verify(argparse.Namespace(bundle=bundle, output=args.output))
    published = dict(state['published'].get('hashes', {}))
    published.update({package: state['catalog'][package]['hash'] for package in state['builds']})
    artifacts.write_json(args.output / 'build-state.json', {
        'schema': 1, 'commit': state['commit'], 'hashes': published,
        'build_release': state['build_release'] + state['wave'],
    })


def pool(args):
    """Carry only the latest canonical binaries into the next wave."""
    planner = load('build-transaction')
    state = json.loads(args.state.read_text())
    for package, build in state['builds'].items():
        for arch in planner.architectures(state):
            source = planner.binary_directory(args.artifacts, package, arch, build['wave'])
            record = planner.checked_binaries(source, package, arch)
            if set(record['binaries']) != {rpm['file'] for rpm in build['targets'][arch]['rpms']}:
                raise ValueError(f'candidate files differ from transaction: {source}')
            destination = args.output / source.relative_to(args.artifacts)
            destination.mkdir(parents=True)
            for rpm in build['targets'][arch]['rpms']:
                if record['binaries'].get(rpm['file']) != rpm['sha256']:
                    raise ValueError(f'candidate differs from transaction: {source}')
                shutil.copy2(source / rpm['file'], destination / rpm['file'])
            shutil.copy2(source / 'source-manifest.json', destination / 'source-manifest.json')


def pack(args):
    """Export only the final, accepted package bytes and their source records."""
    packages = args.output / 'packages'
    stage(argparse.Namespace(state=args.state, artifacts=args.artifacts, output=packages))
    state = json.loads(args.state.read_text())
    if not state['builds'] or not state.get('tree'):
        raise ValueError('candidate has no completed builds or source tree identity')
    for package, build in state['builds'].items():
        source = args.artifacts / f'source-w{build["wave"]}-{package}'
        for name in ('manifest.json', 'test-profile.yaml'):
            shutil.copy2(source / name, packages / package / name)
    shutil.copy2(args.state, args.output / 'state.json')
    artifacts = load('package-artifacts')
    artifacts.write_json(args.output / 'candidate.json', {
        'schema': 1, 'commit': state['commit'], 'tree': state['tree'],
        'rpmx': (ROOT / '.rpmx-revision').read_text().strip(),
        'files': {path.relative_to(args.output).as_posix(): artifacts.digest(path)
                  for path in sorted(args.output.rglob('*')) if path.is_file()},
    })


def verify_candidate(directory, tree, source_sha=None):
    """Validate a portable accepted candidate before any signing or publication."""
    artifacts = load('package-artifacts')
    candidate = json.loads((directory / 'candidate.json').read_text())
    state = json.loads((directory / 'state.json').read_text())
    if (candidate.get('schema') != 1 or candidate.get('tree') != tree
            or state.get('tree') != tree or candidate.get('commit') != state.get('commit')
            or (source_sha and candidate['commit'] != source_sha)
            or candidate.get('rpmx') != (ROOT / '.rpmx-revision').read_text().strip()
            or state.get('pending') or not state.get('builds')
            or not state.get('arches') or set(state['arches']) - {'x86_64', 'aarch64'}
            or set(state.get('repositories', {})) != set(state['arches'])):
        raise ValueError('candidate source, tool or acceptance identity differs')
    actual = set()
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('candidate contains a symbolic link')
        if path.is_file() and path != directory / 'candidate.json':
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(candidate['files']):
        raise ValueError('candidate file inventory differs')
    for name, expected in candidate['files'].items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError('unsafe candidate filename')
        artifacts.verify_file(path, expected)
    for package, build in state['builds'].items():
        if Path(package).name != package or package in ('.', '..'):
            raise ValueError('invalid candidate package')
        bundle = directory / 'packages' / package
        data = artifacts.load_bundle(bundle)
        if data['package'] != package or set(data['targets']) != set(state['arches']):
            raise ValueError('candidate source targets differ')
        artifacts.verify(argparse.Namespace(bundle=bundle, output=directory / 'packages'))
        for arch in state['arches']:
            record = json.loads((bundle / arch / 'source-manifest.json').read_text())
            expected = {rpm['file']: rpm['sha256'] for rpm in build['targets'][arch]['rpms']}
            if (record['binaries'] != expected
                    or record.get('acceptance_repository') != state['repositories'][arch]):
                raise ValueError('candidate acceptance or binary identity differs')
    return state


def rpm_content(path):
    """The immutable header binds package metadata and the payload checksum."""
    identity = subprocess.check_output(['rpm', '-qp', '--qf', '%{SHA256HEADER}', str(path)], text=True)
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('RPM has no immutable header digest')
    return identity


def prepare_release(args):
    """Stage accepted RPMs and unchanged baseline packages without a build."""
    planner = load('build-transaction')
    artifacts = load('package-artifacts')
    commit = subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    state = verify_candidate(args.candidate, tree, args.source_sha)
    if set(state['arches']) != set(planner.ARCHES):
        raise ValueError('release requires every production architecture')
    if args.output.exists():
        raise ValueError('release destination must be a new directory')
    replaced = {rpm['source'] for build in state['builds'].values()
                for target in build['targets'].values() for rpm in target['rpms']}
    published = {}
    retained = set()
    with tempfile.TemporaryDirectory(prefix='eternal-release-') as temporary:
        scratch = Path(temporary)
        # Preserve the baseline outside the candidate's replaced source families.
        for arch in state['arches']:
            repository = scratch / arch
            planner.run('mergerepo_c', '--repo', args.base_url.rstrip('/') + '/rolling/' + arch,
                        '--outputdir', repository, '--no-database', '--nogroups', '--noupdateinfo', '--compress-type=gz')
            baseline = planner.baseline_packages(repository)
            published[arch] = baseline
            identity = lambda entries: sorted((e['name'], e['source'], e['checksum'])
                                              for e in entries if e['source'] not in replaced)
            if identity(baseline) != identity(state['baseline'][arch]):
                raise ValueError('published baseline moved; refresh the candidate before release')
        shutil.copytree(args.candidate / 'packages', args.output)
        downloads = scratch / 'downloads'
        downloads.mkdir()
        for package, build in state['builds'].items():
            for arch, target in build['targets'].items():
                for rpm in target['rpms']:
                    existing = [entry for entry in published[arch]
                                if (entry['name'], entry['evr']) == (rpm['name'], rpm['evr'])]
                    if existing:
                        original = planner.baseline_rpm(existing[0], downloads)
                        destination = args.output / package / arch / rpm['file']
                        if rpm_content(original) != rpm_content(destination):
                            raise ValueError('published RPM identity already has different content')
                        shutil.copy2(original, destination)
                        retained.add(destination)
        for arch in state['arches']:
            for entry in state['baseline'][arch]:
                if entry['source'] not in replaced:
                    source = planner.baseline_rpm(entry, downloads)
                    destination = args.output / '_baseline' / arch / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    retained.add(destination)
        # Source repositories carry all unchanged source families too.
        sources = scratch / 'sources'
        planner.run('mergerepo_c', '--repo', args.base_url.rstrip('/') + '/rolling/SRPMS',
                    '--outputdir', sources, '--no-database', '--nogroups', '--noupdateinfo', '--compress-type=gz')
        for entry in planner.primary(sources):
            location = entry.find('{*}location')
            base = location.get('{http://www.w3.org/XML/1998/namespace}base', '')
            url = urllib.parse.urljoin(base.rstrip('/') + '/', location.get('href'))
            checksum = entry.find('{*}checksum')
            name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
            if not name.endswith('.src.rpm'):
                raise ValueError('invalid published source RPM filename')
            if entry.findtext('{*}name') in replaced:
                matches = [path for path in args.output.glob('*/src/*.src.rpm') if path.name == name]
                if not matches:
                    continue
                destination, = matches
            else:
                destination = args.output / '_baseline' / 'src' / name
            source = planner.baseline_rpm({'url': url, 'checksum': f'{checksum.get("type")}:{checksum.text}'}, downloads)
            if destination.exists() and rpm_content(source) != rpm_content(destination):
                raise ValueError('published source RPM identity already has different content')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            retained.add(destination)
    if args.signing_key:
        for rpm in sorted(args.output.rglob('*.rpm')):
            if rpm not in retained:
                subprocess.run([os.environ.get('RPMX', 'rpmx'), 'sign', '--signing-key', str(args.signing_key), str(rpm)], check=True)
    build_state = json.loads((args.output / 'build-state.json').read_text())
    build_state.update(commit=commit, candidate_commit=state['commit'], tree=tree)
    artifacts.write_json(args.output / 'build-state.json', build_state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    collect_parser = commands.add_parser('collect')
    collect_parser.add_argument('--states', type=Path, required=True)
    collect_parser.set_defaults(function=collect)
    stage_parser = commands.add_parser('stage')
    stage_parser.add_argument('--state', type=Path, required=True)
    stage_parser.add_argument('--artifacts', type=Path, required=True)
    stage_parser.set_defaults(function=stage)
    pack_parser = commands.add_parser('pack')
    pack_parser.add_argument('--state', type=Path, required=True)
    pack_parser.add_argument('--artifacts', type=Path, required=True)
    pack_parser.set_defaults(function=pack)
    pool_parser = commands.add_parser('pool')
    pool_parser.add_argument('--state', type=Path, required=True)
    pool_parser.add_argument('--artifacts', type=Path, required=True)
    pool_parser.set_defaults(function=pool)
    release_parser = commands.add_parser('release')
    release_parser.add_argument('--candidate', type=Path, required=True)
    release_parser.add_argument('--source-sha', required=True)
    release_parser.add_argument('--base-url', required=True)
    release_parser.add_argument('--signing-key', type=Path)
    release_parser.set_defaults(function=prepare_release)
    for command in (collect_parser, stage_parser, pack_parser, pool_parser, release_parser):
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
