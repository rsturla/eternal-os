#!/usr/bin/env python3
"""Prepare shared source RPMs and rebuild their pinned target inputs."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CAS_NAME = re.compile(r'(sha256/[0-9a-f]{64}|sha512/[0-9a-f]{128})')


def digest(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT)


def verify_file(path, expected):
    if digest(path) != expected:
        raise ValueError(f'artifact digest mismatch: {path}')


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def prepare(args):
    import yaml

    recipe = ROOT / 'packages' / args.package / 'package.yaml'
    if not recipe.is_file():
        raise ValueError(f'unknown package: {args.package}')
    if args.output.exists():
        raise ValueError(f'output already exists: {args.output}')
    args.output.mkdir(parents=True)
    bundle = args.output / 'bundle'
    (bundle / 'src').mkdir(parents=True)
    inputs = args.output / 'inputs'
    inputs.mkdir()
    prepared = args.output / 'prepared'
    recipe_hash = subprocess.check_output([str(ROOT / 'scripts/package-hash.sh'), args.package], text=True).split()[1]
    recipe_data = yaml.safe_load(recipe.read_text())
    profile_path = (recipe.parent / recipe_data['build']['root']['profile']).resolve()
    profile = yaml.safe_load(profile_path.read_text())
    transaction = json.loads(args.transaction.read_text()) if args.transaction else None
    if transaction:
        if args.package not in transaction['pending']:
            raise ValueError('package is not pending in this transaction')
        args.build_release = str(transaction['build_release'] + transaction['wave'])
        spec = importlib.util.spec_from_file_location('transaction', ROOT / 'scripts/build-transaction.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        repository_id = digest(args.transaction)
        repository_path = args.cache.resolve().parent / 'transactions' / repository_id / args.package / 'repository'
        if not repository_path.exists():
            module.view(argparse.Namespace(state=args.transaction, artifacts=args.candidates, output=repository_path))
        args.repository_snapshot = repository_path.resolve().as_uri()
    runtime_profile = yaml.safe_load((ROOT / 'profiles/eternal.profile.yaml').read_text())
    command = [args.rpmx, 'srpm', recipe, '--arch', 'all', '--output', prepared, '--cache', args.cache]
    if args.signing_key:
        command += ['--signing-key', args.signing_key]
    if args.build_release:
        command += ['--build-release', args.build_release]
    with tempfile.TemporaryDirectory(prefix='eternal-source-profile-') as scratch:
        if args.repository_snapshot:
            for repository in profile['repositories']:
                if repository.get('id') == 'eternal':
                    repository['baseurl'] = args.repository_snapshot.rstrip('/') + '/$basearch'
            selected = Path(scratch) / 'profile.yaml'
            selected.write_text(yaml.safe_dump(profile, sort_keys=False))
            command += ['--profile', selected]
        # Runtime policy stays separate from the compiler/build-root policy.
        (bundle / 'test-profile.yaml').write_text(yaml.safe_dump(runtime_profile, sort_keys=False))
        run(*command)
    sources = []
    for source in sorted(prepared.glob('*.src.rpm')):
        shutil.copy2(source, bundle / 'src' / source.name)
        sources.append({'file': source.name, 'sha256': digest(source)})
    if not sources:
        raise ValueError('rpmx produced no source RPMs')
    targets = {}
    (bundle / 'locks').mkdir()
    for lock in sorted((prepared / 'locks').glob('root-*.lock.json')):
        arch = lock.name.removeprefix('root-').removesuffix('.lock.json')
        paths = set()
        consumed = set()
        shutil.copy2(lock, bundle / 'locks' / lock.name)
        for target_lock in (prepared / 'locks').glob(f'*-{arch}.lock.json'):
            data = yaml.safe_load(target_lock.read_text())
            for packages in data['packages'].values():
                for package in packages:
                    relative = package['checksum'].replace(':', '/', 1)
                    if not CAS_NAME.fullmatch(relative):
                        raise ValueError(f'invalid CAS name: {relative}')
                    path = args.cache / relative
                    if digest(path, relative.split('/')[0]) != relative.split('/')[1]:
                        raise ValueError(f'corrupt dependency: {relative}')
                    paths.add(relative)
                    if transaction:
                        srpm = package.get('srpm')
                        if srpm and srpm.endswith('.src.rpm'):
                            source_name = srpm[:-8].rsplit('-', 2)[0]
                            consumed.update(provider for provider, metadata in transaction['catalog'].items()
                                            if source_name in metadata['targets'][arch]['sources'])
                        for provider, build in transaction['builds'].items():
                            for candidate in build['targets'][arch]['rpms']:
                                if candidate['name'] == package['name']:
                                    if package['checksum'] != 'sha512:' + candidate['sha512']:
                                        raise ValueError(f'resolver selected an obsolete candidate: {package["name"]}')
                                    consumed.add(provider)
        archive = inputs / f'{arch}.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for relative in sorted(paths):
                tar.add(args.cache / relative, arcname=relative, recursive=False)
        targets[arch] = {'file': archive.name, 'sha256': digest(archive),
                         'lock': digest(bundle / 'locks' / lock.name), 'consumed': sorted(consumed)}
    has_tests = {}
    for arch in targets:
        plan_command = [args.rpmx, 'plan', str(recipe), '--arch', arch, '--json']
        if args.build_release:
            plan_command += ['--build-release', args.build_release]
        plan = json.loads(subprocess.check_output(plan_command, text=True))['plan']
        has_tests[arch] = any(cell['tests'] for cell in plan['cells'])
    write_json(bundle / 'manifest.json', {
        'schema': 1, 'package': args.package, 'rpmx': (ROOT / '.rpmx-revision').read_text().strip(),
        'sources': sources, 'targets': targets, 'has_tests': has_tests, 'recipe_hash': recipe_hash,
        'dist_tag': profile.get('dist-tag'), 'build_release': args.build_release,
        'test_profile': digest(bundle / 'test-profile.yaml'),
        'view': transaction['interfaces'] if transaction else {},
        'repository_id': digest(args.transaction) if transaction else None,
        'repository_path': str(repository_path) if transaction else None,
    })


def import_inputs(archive, cache):
    cache.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if not member.isfile() or not CAS_NAME.fullmatch(member.name):
                raise ValueError(f'invalid dependency archive entry: {member.name}')
            destination = cache / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent) as temporary:
                with tar.extractfile(member) as stream:
                    shutil.copyfileobj(stream, temporary)
                temporary.flush()
                algorithm, expected = member.name.split('/')
                if digest(Path(temporary.name), algorithm) != expected:
                    raise ValueError(f'dependency digest mismatch: {member.name}')
                if destination.is_symlink():
                    raise ValueError(f'CAS destination is a symlink: {destination}')
                shutil.copyfile(temporary.name, destination)


def load_bundle(bundle):
    data = json.loads((bundle / 'manifest.json').read_text())
    if data['schema'] != 1 or not data['sources'] or not data['targets']:
        raise ValueError('invalid source manifest')
    if data['rpmx'] != (ROOT / '.rpmx-revision').read_text().strip():
        raise ValueError('source manifest uses another rpmx revision')
    verify_file(bundle / 'test-profile.yaml', data['test_profile'])
    for source in data['sources']:
        if Path(source['file']).name != source['file'] or not source['file'].endswith('.src.rpm'):
            raise ValueError('invalid source RPM filename')
        verify_file(bundle / 'src' / source['file'], source['sha256'])
    return data


def rebuild(args):
    data = load_bundle(args.bundle)
    recipe_hash = subprocess.check_output([str(ROOT / 'scripts/package-hash.sh'), data['package']], text=True).split()[1]
    if recipe_hash != data['recipe_hash']:
        raise ValueError('recipe inputs differ from the prepared bundle')
    if data.get('repository_id'):
        if not args.transaction or digest(args.transaction) != data['repository_id']:
            raise ValueError('binary build needs the original transaction state')
        repository = args.cache.resolve().parent / 'transactions' / data['repository_id'] / data['package'] / 'repository'
        if str(repository) != data['repository_path']:
            raise ValueError('use the same cache location as source preparation for local repository locks')
        if not repository.exists():
            spec = importlib.util.spec_from_file_location('transaction', ROOT / 'scripts/build-transaction.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.view(argparse.Namespace(state=args.transaction, artifacts=args.candidates, output=repository))
    target = data['targets'][args.arch]
    if target['file'] != f'{args.arch}.tar.gz':
        raise ValueError('invalid target input filename')
    archive = args.inputs / target['file']
    verify_file(archive, target['sha256'])
    import_inputs(archive, args.cache)
    lock = args.bundle / 'locks' / f'root-{args.arch}.lock.json'
    verify_file(lock, target['lock'])
    output = args.output / data['package'] / args.arch
    if output.exists():
        raise ValueError(f'output already exists: {output}')
    output.mkdir(parents=True)
    for source in data['sources']:
        command = [args.rpmx, 'rebuild', args.bundle / 'src' / source['file'],
                   '--arch', args.arch, '--root-lock', lock, '--output', output, '--cache', args.cache]
        if args.signing_key:
            command += ['--signing-key', args.signing_key]
        run(*command)
    binaries = {rpm.name: digest(rpm) for rpm in sorted(output.glob('*.rpm'))}
    if not binaries:
        raise ValueError('rpmx produced no binary RPMs')
    write_json(output / 'source-manifest.json', {
        'schema': 1, 'package': data['package'], 'arch': args.arch,
        'source_manifest': digest(args.bundle / 'manifest.json'), 'binaries': binaries,
        'acceptance': 'pending', 'view': data.get('view', {}),
        'consumed': target.get('consumed', []),
    })


def accept(args):
    import yaml

    data = load_bundle(args.bundle)
    source = args.binaries / data['package'] / args.arch
    record = json.loads((source / 'source-manifest.json').read_text())
    if record['source_manifest'] != digest(args.bundle / 'manifest.json'):
        raise ValueError('acceptance source differs from binary build')
    output = args.output / data['package'] / args.arch
    shutil.copytree(source, output)
    for name, expected in record['binaries'].items():
        if Path(name).name != name:
            raise ValueError('invalid binary filename')
        verify_file(output / name, expected)
        # The subject's bytes in the full candidate pool must be the bytes
        # being accepted, even if a sibling declares the same output name.
        verify_file(args.repository / args.arch / name, expected)
    profile = yaml.safe_load((args.bundle / 'test-profile.yaml').read_text())
    for repository in profile['repositories']:
        if repository['id'] == 'eternal':
            repository['baseurl'] = args.repository.resolve().as_uri() + '/$basearch'
    selected = args.output / 'test-profile.yaml'
    selected.write_text(yaml.safe_dump(profile, sort_keys=False))
    command = [ROOT / 'scripts/accept-rpms.py', ROOT / 'packages' / data['package'] / 'package.yaml',
               '--install-dir', args.repository / args.arch, '--output', output / 'acceptance',
               '--arch', args.arch, '--test-profile', selected]
    if data['build_release']:
        command += ['--build-release', data['build_release']]
    run(*command)
    for name, expected in record['binaries'].items():
        verify_file(output / name, expected)
    record['acceptance'] = 'passed' if data['has_tests'][args.arch] else 'not-required'
    record['acceptance_repository'] = digest(args.repository / args.arch / 'repodata/repomd.xml')
    write_json(output / 'source-manifest.json', record)


def verify(args):
    data = load_bundle(args.bundle)
    for arch in data['targets']:
        directory = args.output / data['package'] / arch
        record = json.loads((directory / 'source-manifest.json').read_text())
        if (record['package'], record['arch'], record['source_manifest']) != (
            data['package'], arch, digest(args.bundle / 'manifest.json')
        ):
            raise ValueError(f'build source differs for {arch}')
        expected_acceptance = 'passed' if data['has_tests'][arch] else 'not-required'
        if record['acceptance'] != expected_acceptance:
            raise ValueError(f'package acceptance did not pass for {arch}')
        if not record['binaries'] or set(record['binaries']) != {rpm.name for rpm in directory.glob('*.rpm')}:
            raise ValueError(f'incomplete binary artifact for {arch}')
        for name, expected in record['binaries'].items():
            if Path(name).name != name:
                raise ValueError('invalid binary filename')
            verify_file(directory / name, expected)
    sources = args.output / data['package'] / 'src'
    sources.mkdir(exist_ok=True)
    for source in data['sources']:
        original = args.bundle / 'src' / source['file']
        destination = sources / source['file']
        if original.resolve() != destination.resolve():
            shutil.copy2(original, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='operation', required=True)
    for name, function in [('prepare', prepare), ('rebuild', rebuild), ('accept', accept), ('verify', verify)]:
        command = subparsers.add_parser(name)
        command.set_defaults(function=function)
        command.add_argument('--output', type=Path, required=True)
        if name == 'prepare':
            command.add_argument('--package', required=True)
            command.add_argument('--build-release')
            command.add_argument('--repository-snapshot')
            command.add_argument('--transaction', type=Path)
            command.add_argument('--candidates', type=Path)
        else:
            command.add_argument('--bundle', type=Path, required=True)
        if name == 'rebuild':
            command.add_argument('--arch', choices=['x86_64', 'aarch64'], required=True)
            command.add_argument('--inputs', type=Path, required=True)
            command.add_argument('--transaction', type=Path)
            command.add_argument('--candidates', type=Path)
        if name == 'accept':
            command.add_argument('--arch', choices=['x86_64', 'aarch64'], required=True)
            command.add_argument('--binaries', type=Path, required=True)
            command.add_argument('--repository', type=Path, required=True)
        if name in ('prepare', 'rebuild'):
            command.add_argument('--cache', type=Path, default=Path.home() / '.cache/rpmx/cas')
            command.add_argument('--rpmx', default=os.environ.get('RPMX', 'rpmx'))
            command.add_argument('--signing-key', type=Path)
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
