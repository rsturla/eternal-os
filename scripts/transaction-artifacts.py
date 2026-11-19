#!/usr/bin/env python3
"""Select the final transaction and stage its tested artifacts for publication."""

import argparse
import importlib.util
import json
from pathlib import Path
import shutil

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
    for command in (collect_parser, stage_parser, pack_parser, pool_parser):
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
