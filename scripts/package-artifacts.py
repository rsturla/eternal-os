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
import sys
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
CAS_NAME = re.compile(r'(sha256/[0-9a-f]{64}|sha512/[0-9a-f]{128})')


def digest(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT)


def fetch_sources(rpmx, recipe, cache):
    """Retry network acquisition without repeating assembly or build steps."""
    command = list(map(str, [rpmx, 'fetch', recipe, '--cache', cache, '--json']))
    for delay in (15, 45, None):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        print(result.stdout, end='', flush=True)
        print(result.stderr, end='', file=sys.stderr, flush=True)
        if result.returncode == 0:
            return
        try:
            errors = [item for item in json.loads(result.stdout)['diagnostics'] if item['severity'] == 'error']
            retryable = bool(errors) and all(
                item['code'] == 'RPMX-FETCH-003' and item['message'].startswith(
                    ('GET ', 'proxy request failed:')) for item in errors)
        except (ValueError, KeyError, TypeError):
            retryable = False
        if not retryable or delay is None:
            result.check_returncode()
        print(f'Source acquisition failed; retrying in {delay}s', file=sys.stderr, flush=True)
        time.sleep(delay)


def verify_file(path, expected):
    if digest(path) != expected:
        raise ValueError(f'artifact digest mismatch: {path}')


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def verify_candidate(path, candidate):
    # Repository primary metadata uses SHA-256. Transaction receipts also keep
    # SHA-512. Compare the same bytes with the receipt's algorithm, rather than
    # comparing digest strings produced with different algorithms.
    if digest(path, 'sha512') != candidate['sha512']:
        raise ValueError(f'resolver selected an obsolete candidate: {candidate["name"]}')


def consumed_providers(path, package, transaction, arch):
    # A seed RPM can have the same name and SRPM family as an Eternal RPM.
    # Only inputs resolved from the frozen Eternal view consume candidates.
    if package['origin'].get('repository') != 'eternal':
        return set()
    consumed = set()
    srpm = package.get('srpm')
    if srpm and srpm.endswith('.src.rpm'):
        source_name = srpm[:-8].rsplit('-', 2)[0]
        consumed.update(provider for provider, metadata in transaction['catalog'].items()
                        if source_name in metadata['targets'][arch]['sources'])
    for provider, build in transaction['builds'].items():
        for candidate in build['targets'][arch]['rpms']:
            if candidate['name'] == package['name']:
                verify_candidate(path, candidate)
                consumed.add(provider)
    return consumed


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
        if recipe_hash != transaction['catalog'][args.package]['hash']:
            raise ValueError('recipe inputs differ from the transaction snapshot')
        args.build_release = str(transaction['build_release'] + transaction['wave'])
        spec = importlib.util.spec_from_file_location('transaction', ROOT / 'scripts/build-transaction.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        repository_id = digest(args.transaction)
        shutil.copy2(args.transaction, bundle / 'transaction.json')
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
        fetch_sources(args.rpmx, recipe, args.cache)
        run(*command)
    sources = []
    for source in sorted(prepared.glob('*.src.rpm')):
        shutil.copy2(source, bundle / 'src' / source.name)
        sources.append({'file': source.name, 'sha256': digest(source)})
    if not sources:
        raise ValueError('rpmx produced no source RPMs')
    targets = {}
    (bundle / 'inputs').mkdir()
    for record in sorted((prepared / 'inputs').glob('*.json')):
        arch = record.stem
        data = json.loads(record.read_text())
        paths = set()
        consumed = set()
        shutil.copy2(record, bundle / 'inputs' / record.name)
        # rpmx owns the inventory across build, sysroot, toolchain and test roles.
        for checksum in data['payloads']:
            relative = checksum.replace(':', '/', 1)
            if not CAS_NAME.fullmatch(relative):
                raise ValueError(f'invalid CAS name: {relative}')
            path = args.cache / relative
            if digest(path, relative.split('/')[0]) != relative.split('/')[1]:
                raise ValueError(f'corrupt dependency: {relative}')
            paths.add(relative)
        if transaction:
            roots = [data['inputs']['root'], data['inputs'].get('sysroot')]
            roots.extend((data['inputs'].get('tests') or {}).values())
            for root in filter(None, roots):
                for packages in root['packages'].values():
                    for package in packages:
                        relative = package['checksum'].replace(':', '/', 1)
                        if relative not in paths:
                            raise ValueError(f'dependency missing from inventory: {relative}')
                        consumed.update(consumed_providers(args.cache / relative, package, transaction, arch))
        archive = inputs / f'{arch}.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for relative in sorted(paths):
                tar.add(args.cache / relative, arcname=relative, recursive=False)
        targets[arch] = {'file': archive.name, 'sha256': digest(archive),
                         'inputs': digest(bundle / 'inputs' / record.name), 'consumed': sorted(consumed)}
    if not targets:
        raise ValueError('rpmx produced no target input records')
    has_tests = {}
    for arch in targets:
        plan_command = [args.rpmx, 'plan', str(recipe), '--arch', arch, '--json']
        if args.build_release:
            plan_command += ['--build-release', args.build_release]
        plan = json.loads(subprocess.check_output(plan_command, text=True))['plan']
        has_tests[arch] = any(cell['tests'] for cell in plan['cells'])
    write_json(bundle / 'manifest.json', {
        'schema': 2, 'package': args.package, 'rpmx': (ROOT / '.rpmx-revision').read_text().strip(),
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
    if data['schema'] != 2 or not data['sources'] or not data['targets']:
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
    # The verified input archive contains the complete locked CAS closure.
    # Rebuilding does not resolve repositories or need the source worker's
    # filesystem. A fresh worker may use a different cache location.
    target = data['targets'][args.arch]
    if target['file'] != f'{args.arch}.tar.gz':
        raise ValueError('invalid target input filename')
    archive = args.inputs / target['file']
    verify_file(archive, target['sha256'])
    record = args.bundle / 'inputs' / f'{args.arch}.json'
    verify_file(record, target['inputs'])
    import_inputs(archive, args.cache)
    output = args.output / data['package'] / args.arch
    if output.exists():
        raise ValueError(f'output already exists: {output}')
    output.mkdir(parents=True)
    for source in data['sources']:
        command = [args.rpmx, 'rebuild', args.bundle / 'src' / source['file'],
                   '--arch', args.arch, '--inputs', record, '--output', output, '--cache', args.cache]
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


def accept_batch(args):
    state = json.loads(args.state.read_text())
    packages = json.loads(args.packages)
    if (state['pending'] or not state.get('repositories') or args.arch not in state['arches']
            or not isinstance(packages, list) or not packages
            or any(not isinstance(package, str) for package in packages)
            or len(set(packages)) != len(packages) or set(packages) - state['builds'].keys()):
        raise ValueError('invalid acceptance batch or unfinished transaction')
    if digest(args.repository / args.arch / 'repodata/repomd.xml') != state['repositories'][args.arch]:
        raise ValueError('acceptance repository differs from the sealed transaction')
    for package in packages:
        wave = state['builds'][package]['wave']
        accept(argparse.Namespace(bundle=args.artifacts / f'source-w{wave}-{package}',
                                  binaries=args.artifacts / f'binary-w{wave}-{package}-{args.arch}',
                                  repository=args.repository, arch=args.arch,
                                  output=args.output / f'accepted-{package}-{args.arch}'))


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
    for name, function in [('prepare', prepare), ('rebuild', rebuild), ('accept', accept),
                           ('accept-batch', accept_batch), ('verify', verify)]:
        command = subparsers.add_parser(name)
        command.set_defaults(function=function)
        command.add_argument('--output', type=Path, required=True)
        if name == 'prepare':
            command.add_argument('--package', required=True)
            command.add_argument('--build-release')
            command.add_argument('--repository-snapshot')
            command.add_argument('--transaction', type=Path)
            command.add_argument('--candidates', type=Path)
        elif name != 'accept-batch':
            command.add_argument('--bundle', type=Path, required=True)
        if name == 'rebuild':
            command.add_argument('--arch', choices=['x86_64', 'aarch64'], required=True)
            command.add_argument('--inputs', type=Path, required=True)
            command.add_argument('--transaction', type=Path)
        if name == 'accept':
            command.add_argument('--arch', choices=['x86_64', 'aarch64'], required=True)
            command.add_argument('--binaries', type=Path, required=True)
            command.add_argument('--repository', type=Path, required=True)
        if name == 'accept-batch':
            command.add_argument('--state', type=Path, required=True)
            command.add_argument('--artifacts', type=Path, required=True)
            command.add_argument('--packages', required=True, help='JSON array of source package names')
            command.add_argument('--arch', choices=['x86_64', 'aarch64'], required=True)
            command.add_argument('--repository', type=Path, required=True)
        if name in ('prepare', 'rebuild'):
            command.add_argument('--cache', type=Path, default=Path.home() / '.cache/rpmx/cas')
            command.add_argument('--rpmx', default=os.environ.get('RPMX', 'rpmx'))
            command.add_argument('--signing-key', type=Path)
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
