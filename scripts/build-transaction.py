#!/usr/bin/env python3
"""Plan dependency rebuilds and assemble fixed repository views for one main build."""

import argparse
import ast
import fnmatch
import gzip
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ARCHES = ('x86_64', 'aarch64')
RPMX = os.environ.get('RPMX', 'rpmx')
_PROVENANCE_SPEC = importlib.util.spec_from_file_location('build_provenance', ROOT / 'scripts/build-provenance.py')
provenance = importlib.util.module_from_spec(_PROVENANCE_SPEC)
_PROVENANCE_SPEC.loader.exec_module(provenance)


_INPUTS_SPEC = importlib.util.spec_from_file_location('recipe_inputs', ROOT / 'scripts/recipe-inputs.py')
recipe_inputs = importlib.util.module_from_spec(_INPUTS_SPEC)
_INPUTS_SPEC.loader.exec_module(recipe_inputs)


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


def architectures(state):
    return state.get('arches', ARCHES)


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


def read_remote(url, consume):
    """Retry a complete GET, including failures while reading its response."""
    for delay in (15, 45, None):
        try:
            with open_url(url) as response:
                return consume(response)
        except (urllib.error.URLError, ConnectionError, TimeoutError, http.client.IncompleteRead) as error:
            if isinstance(error, urllib.error.HTTPError):
                retryable = error.code in (408, 429, 500, 502, 503, 504)
                error.close()
            elif isinstance(error, urllib.error.URLError):
                retryable = isinstance(error.reason, (ConnectionError, TimeoutError)) or (
                    isinstance(error.reason, socket.gaierror) and error.reason.errno == socket.EAI_AGAIN)
            else:
                retryable = True
            if not retryable or delay is None:
                raise
            print(f'Repository download failed; retrying in {delay}s: {error}', file=sys.stderr, flush=True)
            time.sleep(delay)


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


def catalog(arches=ARCHES):
    import yaml
    hashes = dict(line.split() for line in capture(ROOT / 'scripts/package-hash.sh').splitlines())
    result = {}
    for recipe in sorted((ROOT / 'packages').glob('*/package.yaml')):
        document = yaml.safe_load(recipe.read_text())
        profile = yaml.safe_load((recipe.parent / document['build']['root']['profile']).read_text())
        candidate_repository = next((repository for repository in profile['repositories']
                                     if repository['id'] == 'eternal'), None)
        targets = {}
        for arch in arches:
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
                'build_requires': sorted({capability(value) for cell in cells for value in cell['packages'] + cell['sysroot']} |
                                         {capability(value) for cell in cells for step in cell['pipeline']
                                          for value in step['needs_packages'] + step['needs_sysroot']} |
                                         {capability(value) for value in profile.get('packages', {}).get('install', [])} |
                                         {capability(value) for cell in cells for test in cell.get('build_tests', [])
                                          if not test.get('optional', False) for value in test.get('packages', [])}),
                'candidate_repository': ({'exclude': candidate_repository.get('exclude', [])}
                                         if candidate_repository is not None else None),
                'outputs': [{'name': output['name'], 'provides': sorted({output['name']} |
                             {capability(value) for value in output['provides']})} for output in outputs],
            }
        result[recipe.parent.name] = {'hash': hashes[recipe.parent.name], 'targets': targets}
    return result


def initialise(args):
    import yaml
    if args.state.exists():
        raise ValueError(f'transaction already exists: {args.state}')
    arch = getattr(args, 'arch', 'all')
    arches = ARCHES if arch == 'all' else (arch,)
    recipes = catalog(arches)
    previous = {'hashes': {}}
    if args.published:
        try:
            previous = read_remote(args.published.rstrip('/') + '/build-state.json', json.load)
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
    for arch in arches:
        repository = args.state.parent / 'baseline' / arch
        run('mergerepo_c', '--repo', args.base_url.rstrip('/') + '/rolling/' + arch,
            '--outputdir', repository, '--no-database', '--nogroups', '--noupdateinfo', '--compress-type=gz')
        baseline[arch] = baseline_packages(repository)
    requirements = provenance.load()
    repair_reasons = {}
    if requirements:
        with tempfile.TemporaryDirectory(prefix='eternal-provenance-') as temporary:
            for arch in arches:
                for entry in baseline[arch]:
                    receipt = provenance.read(baseline_rpm(entry, Path(temporary)))
                    reasons = provenance.failures(receipt, requirements, arch)
                    if reasons:
                        owners = [name for name, recipe in recipes.items() if entry['source'] in recipe['targets'][arch]['sources']]
                        if not owners:
                            raise ValueError(f'external baseline package needs repaired build inputs: {entry["name"]}: {reasons}')
                        for owner in owners:
                            repair_reasons.setdefault(owner, []).extend(reasons)
        selected = sorted(set(selected) | repair_reasons.keys())
    policy = yaml.safe_load((ROOT / 'rebuild-policy.yaml').read_text()) or {}
    for provider, consumers in policy.items():
        if provider not in recipes or not isinstance(consumers, list) or set(consumers) - recipes.keys() - {'*'}:
            raise ValueError(f'invalid rebuild policy: {provider}')
    state = {'schema': 1, 'arches': list(arches), 'commit': args.commit, 'tree': capture('git', '-C', ROOT, 'rev-parse', 'HEAD^{tree}').strip(), 'catalog': recipes, 'baseline': baseline,
                       'published': previous, 'requirements': requirements, 'policy': policy, 'pending': selected, 'wave': 0,
                       'build_release': args.build_release, 'builds': {}, 'interfaces': {},
                       'baseline_interfaces': {}, 'requested': selected,
                       'reasons': {name: repair_reasons.get(name, ['recipe inputs changed']) for name in selected}}
    state['pending'] = select_wave(state, args, set(selected))
    write(args.state, state)
    emit(state)


def build_inputs(tree, package):
    """Compare tracked build inputs independently of scheduling and Git history.

    Locked SRPM execution stays in package-artifacts.py and rpmx. Scheduling,
    transport and export scripts do not change that execution. Everything else
    in scripts/ remains an input, so new or unknown build helpers fail closed.
    """
    scheduling = {'scripts/actions-build.py', 'scripts/build-waves.py', 'scripts/transaction-artifacts.py',
                  'scripts/publish-repo.sh', 'scripts/publish-bucket.sh'}
    paths = [f'packages/{package}', 'packages/openssf-compiler-options', 'profiles',
             'scripts', '.rpmx-revision', 'rpmx-defaults.yaml']
    entries = capture('git', '-C', ROOT, 'ls-tree', '-rz', tree, '--', *paths)
    result = {path: metadata for entry in entries.split('\0') if entry
              for metadata, path in [entry.split('\t', 1)] if path not in scheduling}
    planner = 'scripts/build-transaction.py'
    if planner in result:
        # Repo assembly and ABI interpretation are build inputs even though
        # they share a file with scheduling. Unknown functions stay inputs.
        scheduling_functions = {'initialise', 'reuse', 'build_inputs', 'next_packages',
                                'ready_packages', 'select_wave', 'advance', 'main', 'emit'}
        syntax = ast.parse(capture('git', '-C', ROOT, 'show', f'{tree}:{planner}'))
        syntax.body = [node for node in syntax.body
                       if not isinstance(node, ast.FunctionDef) or node.name not in scheduling_functions]
        syntax.body = [node for node in syntax.body if not (
            isinstance(node, ast.Import) and all(alias.name == 'ast' for alias in node.names))]
        result[planner] = hashlib.sha256(ast.dump(syntax).encode()).hexdigest()
    return result


def reuse(args):
    """Carry verified builds into a new source tree; accept everything again."""
    if args.state.exists():
        raise ValueError(f'transaction already exists: {args.state}')
    if capture('git', '-C', ROOT, 'rev-parse', 'HEAD').strip() != args.commit or capture(
            'git', '-C', ROOT, 'status', '--porcelain', '--untracked-files=normal').strip():
        raise ValueError('reuse requires a clean checkout of the new commit')
    state = json.loads(args.previous.read_text())
    if state.get('schema') != 1 or state['pending'] or not state['builds']:
        raise ValueError('reuse needs a settled build transaction')
    old_tree = capture('git', '-C', ROOT, 'rev-parse', state['commit'] + '^{tree}').strip()
    if old_tree != state['tree']:
        raise ValueError('reused source tree differs from its commit')
    tree = capture('git', '-C', ROOT, 'rev-parse', args.commit + '^{tree}').strip()
    for path in ('rebuild-policy.yaml', 'rebuild-requirements.yaml'):
        if capture('git', '-C', ROOT, 'rev-parse', f'{old_tree}:{path}') != capture(
                'git', '-C', ROOT, 'rev-parse', f'{tree}:{path}'):
            raise ValueError('rebuild policy changed; start a fresh transaction')
    recipes = catalog(architectures(state))
    if set(state['catalog']) - recipes.keys():
        raise ValueError('recipes were removed; start a fresh transaction')
    changed = sorted(name for name in recipes
                     if build_inputs(old_tree, name) != build_inputs(tree, name))
    for arch in architectures(state):
        baseline = args.previous.parent / 'baseline' / arch
        if baseline_packages(baseline) != state['baseline'][arch]:
            raise ValueError('reused baseline metadata differs from the transaction')
        for package, build in state['builds'].items():
            directory = binary_directory(args.artifacts, package, arch, build['wave'])
            record = checked_binaries(directory, package, arch)
            expected = {rpm['file']: rpm['sha256'] for rpm in build['targets'][arch]['rpms']}
            if record['binaries'] != expected:
                raise ValueError(f'reused candidate differs from transaction: {package}/{arch}')
    state['reused_from'] = {'commit': state['commit'], 'tree': old_tree,
                          'packages': sorted(set(state['builds']) - set(changed))}
    state.update(commit=args.commit, tree=tree, catalog=recipes, invalidated=changed,
                 wave_start=state['wave'],
                 build_release=max(args.build_release, state['build_release'] + state['wave'] + 1))
    state.pop('repositories', None)
    state['requested'] = sorted(set(state['requested']) | (recipes.keys() - state['builds'].keys()))
    state['reasons'] = next_packages(state)
    shutil.copytree(args.previous.parent / 'baseline', args.state.parent / 'baseline')
    state['pending'] = select_wave(state, args, set(state['reasons']))
    write(args.state, state)
    emit(state)


def archive_fingerprint(stream):
    """Compare archive contents and order without member timestamps or owners."""
    signature = stream.read(8)
    result = hashlib.sha256(signature)
    if signature != b'!<arch>\n':
        # A linker script or another format named .a keeps its exact digest.
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
        return result.hexdigest()
    while header := stream.read(60):
        if len(header) != 60 or header[-2:] != b'`\n':
            raise ValueError('invalid static archive member header')
        size = int(header[48:58])
        if size < 0:
            raise ValueError('invalid static archive member size')
        result.update(header[:16] + b' ' * 24 + header[40:])
        remaining = size + size % 2
        while remaining:
            chunk = stream.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError('truncated static archive member')
            result.update(chunk)
            remaining -= len(chunk)
    return result.hexdigest()


def static_archives(path, names):
    if not names:
        return {}
    result = {}
    with path.open('rb') as source, subprocess.Popen(
            ['rpm2archive', '-n', '-'], stdin=source, stdout=subprocess.PIPE) as process:
        with tarfile.open(fileobj=process.stdout, mode='r|') as payload:
            for entry in payload:
                name = '/' + entry.name.removeprefix('./').lstrip('/')
                if name in names and entry.isfile():
                    result[name] = archive_fingerprint(payload.extractfile(entry))
        # Consume tar padding before waiting for the producer.
        process.stdout.read()
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, process.args)
    return result


def inspect_rpm(path):
    def query(format):
        return capture('rpm', '-qp', '--qf', format, path).splitlines()
    name, source, arch = query('%{NAME}\n%{SOURCERPM}\n%{ARCH}\n')
    evr = query('%{EPOCHNUM}\n%{VERSION}\n%{RELEASE}\n')
    provides = query('[%{PROVIDENAME}\n]')
    provider_capabilities = query('[%{PROVIDENAME} = %{PROVIDEVERSION}\n]')
    # A changed public library payload is a possible ABI change. Headers and
    # static libraries also invalidate consumers. This deliberately overbuilds
    # rather than claiming that matching SONAMEs prove ABI compatibility.
    sonames = {value.split('(')[0] for value in provides if '.so' in value}
    public = []
    payload = []
    files = [shlex.split(line) for line in capture('rpm', '-qp', '--dump', path).splitlines()]
    archives = static_archives(path, {fields[0] for fields in files if fields[0].endswith('.a')})
    for fields in files:
        filename, checksum = fields[0], fields[3]
        checksum = archives.get(filename, checksum)
        if not filename.startswith(('/usr/share/sbom/', '/usr/share/rpmx/buildinfo/')):
            payload.append([filename, checksum, fields[4], fields[-1]])
        if (Path(filename).name in sonames or
                any(Path(filename).name.startswith(soname + '.') for soname in sonames) or
                '/include/' in filename or filename.endswith('.a')):
            public.append([filename, checksum, fields[4], fields[-1]])
    interface = {'provides': sorted(value for value in provides if '.so' in value), 'files': sorted(public)}
    return {'name': name, 'source': source_name(source), 'arch': arch, 'evr': evr,
            'provides': provides, 'requires': query('[%{REQUIRENAME}\n]'),
            'provider_capabilities': sorted(value for value in provider_capabilities if value.startswith('rpmx(')),
            'interface': interface, 'payload': sorted(payload), 'sha512': digest(path, 'sha512'), 'sha256': digest(path), 'file': path.name}


def fingerprint(records, all_files=False):
    # Ignore RPM release counters, timestamps and package digests.
    public = ({record['name']: record['payload'] for record in records} if all_files else
              {record['name']: record['interface'] for record in records
               if record['interface']['provides'] or record['interface']['files']})
    # Portable providers may change compiler output, embedded code or generated
    # sources without changing ELF interfaces. Ignore receipts and signatures.
    providers = {record['name']: {'capabilities': record['provider_capabilities'], 'payload': record['payload']}
                 for record in records if record.get('provider_capabilities')}
    return hashlib.sha256(json.dumps([public, providers], sort_keys=True).encode()).hexdigest()


def baseline_rpm(entry, directory):
    algorithm, expected = entry['checksum'].split(':', 1)
    path = directory / (expected + '.rpm')
    if not path.exists():
        def acquire(response):
            with tempfile.TemporaryDirectory(prefix='.download-', dir=directory) as temporary:
                staged = Path(temporary) / 'package.rpm'
                with staged.open('wb') as output:
                    shutil.copyfileobj(response, output)
                length = response.headers.get('Content-Length')
                if length is not None and staged.stat().st_size != int(length):
                    raise http.client.IncompleteRead(b'', int(length) - staged.stat().st_size)
                if digest(staged, algorithm) != expected:
                    raise ValueError(f'published package checksum mismatch: {entry["url"]}')
                staged.replace(path)
        read_remote(entry['url'], acquire)
        return path
    if digest(path, algorithm) != expected:
        raise ValueError(f'published package checksum mismatch: {entry["url"]}')
    return path


def verify_repairs(state, artifacts, requirements=None):
    """Verify exact candidate bytes and unchanged baseline before acceptance."""
    requirements = provenance.load() if requirements is None else requirements
    if not requirements:
        return
    with tempfile.TemporaryDirectory(prefix='eternal-repair-gate-') as temporary:
        for arch in architectures(state):
            replaced = set()
            for package, build in state['builds'].items():
                # Promotion and queue stage into the canonical package layout;
                # native workers still use their wave artifact directories.
                directory = artifacts / package / arch
                if not directory.exists():
                    directory = binary_directory(artifacts, package, arch, build['wave'])
                for rpm in build['targets'][arch]['rpms']:
                    path = directory / rpm['file']
                    if digest(path) != rpm['sha256']:
                        raise ValueError(f'changed repair candidate: {path}')
                    provenance.verify(path, requirements, arch)
                    replaced.add(rpm['source'])
            for entry in state['baseline'][arch]:
                if entry['source'] not in replaced:
                    provenance.verify(baseline_rpm(entry, Path(temporary)), requirements, arch)


def baseline_interface(state, package, arch, directory):
    records = []
    sources = state['catalog'][package]['targets'][arch]['sources']
    for entry in state['baseline'][arch]:
        if entry['source'] not in sources:
            continue
        path = baseline_rpm(entry, directory)
        records.append(inspect_rpm(path))
    return fingerprint(records, package in state['policy'])


def planned_provides(state, provider, arch, repository):
    """Potential providers for graph edges, including outputs not yet built."""
    if repository is None:
        return set()
    target = state['catalog'][provider]['targets'][arch]
    records = list(state['baseline'][arch])
    if provider in state['builds']:
        records += state['builds'][provider]['targets'][arch]['rpms']
    provides = set()
    for output in target['outputs']:
        name = output['name']
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in repository.get('exclude', [])):
            continue
        provides.update(output['provides'])
        for record in records:
            if record['name'] == name and record['source'] in target['sources']:
                provides.update(record['provides'])
    return provides


def dependencies(state, package, arch):
    target = state['catalog'][package]['targets'][arch]
    requires = set(target['requires'])
    input_capabilities = set()
    for record in state['baseline'][arch]:
        if record['source'] in target['sources']:
            input_capabilities.update('rpmx(' + value[len('buildinput('):] for value in record['provides'] if value.startswith('buildinput('))
    for record in state['baseline'][arch]:
        if record['source'] in target['sources']:
            requires.update(record['requires'])
    build = state['builds'].get(package)
    if build:
        requires.update(build['targets'][arch]['requires'])
    result = set()
    for provider in state['catalog']:
        provides = planned_provides(state, provider, arch, target['candidate_repository'])
        if requires & provides or input_capabilities & provides or package in state['policy'].get(provider, []) or '*' in state['policy'].get(provider, []):
            result.add(provider)
    if build:
        result.update(build['targets'][arch]['consumed'])
    return result - {package}


def next_packages(state):
    reasons = {name: {'recipe inputs changed'} for name in state.get('requested', []) if name not in state['builds']}
    for name in state.get('invalidated', []):
        reasons.setdefault(name, set()).add('recipe inputs changed')
    for package in state['catalog']:
        for arch in architectures(state):
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


def build_dependencies(state, package, arch):
    """Order builds by inputs available through their candidate repository.

    Runtime dependencies still invalidate consumers, but do not define build
    order. A recipe using only seed repositories cannot consume candidates.
    Apply the same profile filters as the resolver before matching providers.
    """
    target = state['catalog'][package]['targets'][arch]
    repository = target['candidate_repository']
    if repository is None:
        return set()
    requires = set(target['build_requires'])
    result = set()
    for provider in state['catalog']:
        if package in state['policy'].get(provider, []) or '*' in state['policy'].get(provider, []):
            result.add(provider)
        if requires & planned_provides(state, provider, arch, repository):
            result.add(provider)
    return result - {package}


def ready_packages(state, waiting):
    """Find dependency-closed graph candidates; readiness is checked separately."""
    edges = {package: set().union(*(build_dependencies(state, package, arch) for arch in architectures(state))) & waiting
             for package in waiting}
    # A package is ready if everything it waits for can reach it. Those edges
    # form a cycle. select_wave checks which members can use existing RPMs.
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


def select_wave(state, args, waiting):
    """Gate graph candidates on real input resolution against one fixed view."""
    eligible = ready_packages(state, waiting)
    state['blocked'] = {}
    if not waiting:
        return []
    ready = []
    artifacts = getattr(args, 'artifacts', Path('.work/candidates'))
    cache = getattr(args, 'cache', Path(os.environ.get('RPMX_CACHE', Path.home() / '.cache/rpmx/cas')))
    with tempfile.TemporaryDirectory(prefix='eternal-readiness-') as temporary:
        repository = Path(temporary) / 'repository'
        view(argparse.Namespace(state=args.state, artifacts=artifacts, output=repository), state=state)
        for package in eligible:
            failures = {}
            for arch in architectures(state):
                evidence = args.state.parent / 'readiness' / f'wave-{state["wave"]}' / package / arch
                if evidence.exists():
                    shutil.rmtree(evidence)
                print(f'Checking inputs for {package}/{arch}', file=sys.stderr, flush=True)
                failure = recipe_inputs.resolve(RPMX, ROOT / 'packages' / package / 'package.yaml',
                    arch, repository.resolve().as_uri(), cache, evidence,
                    state['build_release'] + state['wave'])
                if failure:
                    failures[arch] = failure
            if failures:
                state['blocked'][package] = {'providers': sorted(set().union(*(
                    build_dependencies(state, package, arch) for arch in architectures(state)))),
                    'targets': failures}
            else:
                ready.append(package)
    if not ready:
        details = json.dumps(state['blocked'], sort_keys=True, indent=2)
        raise ValueError(f'no buildable package in the dependency closure; '
                         f'provide a compatible seed or explicit bootstrap stage:\n{details}')
    return ready


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
            for arch in architectures(state):
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
        state['interfaces'][package] = {arch: state['builds'][package]['targets'][arch]['fingerprint'] for arch in architectures(state)}
    state['invalidated'] = sorted(set(state.get('invalidated', [])) - set(state['pending']))
    state['reasons'] = next_packages(state)
    state['wave'] += 1
    state['pending'] = select_wave(state, args, set(state['reasons']))
    if state['pending'] and (args.final or state['wave'] - state.get('wave_start', 0) >= 32):
        raise ValueError(f'rebuild closure did not settle: {state["reasons"]}')
    write(args.state, state)
    emit(state)


def emit(state):
    print(json.dumps({'packages': state['pending'], 'wave': state['wave'],
                      'complete': not state['pending'], 'built': sorted(state['builds'])}, separators=(',', ':')))


def localise_repository(repository):
    """Make file-backed baseline entries portable within the snapshot.

    DNF escapes '+' in file:// xml:base locations but then opens the escaped
    filename literally. Use checksum filenames and the snapshot's own base.
    HTTP locations stay remote and retain their original URLs.
    """
    metadata = primary(repository)
    changed = False
    for entry in metadata:
        location = entry.find('{*}location')
        base = location.get('{http://www.w3.org/XML/1998/namespace}base', '')
        if not base.startswith('file:'):
            continue
        url = urllib.parse.urlparse(urllib.parse.urljoin(base.rstrip('/') + '/', location.get('href')))
        if url.netloc not in ('', 'localhost'):
            raise ValueError('file repository must be local')
        source = Path(urllib.parse.unquote(url.path))
        checksum = entry.find('{*}checksum')
        if digest(source, checksum.get('type')) != checksum.text:
            raise ValueError(f'local baseline checksum mismatch: {source}')
        filename = checksum.text + '.rpm'
        shutil.copy2(source, repository / filename)
        location.set('href', filename)
        location.attrib.pop('{http://www.w3.org/XML/1998/namespace}base')
        changed = True
    if changed:
        with tempfile.TemporaryDirectory(prefix='eternal-local-repo-') as temporary:
            xml = Path(temporary) / 'primary.xml'
            ET.register_namespace('', 'http://linux.duke.edu/metadata/common')
            ET.register_namespace('rpm', 'http://linux.duke.edu/metadata/rpm')
            ET.ElementTree(metadata).write(xml, encoding='utf-8', xml_declaration=True)
            run('modifyrepo_c', '--mdtype', 'primary', '--compress', '--compress-type=gz',
                '--unique-md-filenames', xml, repository / 'repodata')


def view(args, state=None):
    if state is None:
        state = json.loads(args.state.read_text())
    spec = importlib.util.spec_from_file_location('filter_rolling', ROOT / 'scripts/filter-rolling.py')
    filtering = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(filtering)
    for arch in architectures(state):
        destination = args.output / arch
        if not state['builds']:
            shutil.copytree(args.state.parent / 'baseline' / arch, destination)
            localise_repository(destination)
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
                href = location.get('href')
                filename = Path(urllib.parse.unquote(href)).name
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
            localise_repository(destination)


def seal(args):
    state = json.loads(args.state.read_text())
    if state['pending']:
        raise ValueError('cannot accept an unfinished rebuild closure')
    verify_repairs(state, args.artifacts)
    view(args)
    state['repositories'] = {arch: digest(args.output / arch / 'repodata/repomd.xml') for arch in architectures(state)}
    write(args.state, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest='operation', required=True)
    for name, function in [('init', initialise), ('reuse', reuse), ('advance', advance), ('view', view), ('seal', seal)]:
        command = operations.add_parser(name)
        command.add_argument('--state', type=Path, required=True)
        if name in ('init', 'reuse', 'advance'):
            command.add_argument('--cache', type=Path, default=Path(os.environ.get('RPMX_CACHE', Path.home() / '.cache/rpmx/cas')))
        command.set_defaults(function=function)
        if name == 'init':
            command.add_argument('--arch', choices=['all', *ARCHES], default='all')
            command.add_argument('--packages', default='changed', help='changed or a JSON array')
            command.add_argument('--base-url', default='https://packages.eternal.sturla.tech')
            command.add_argument('--published', help='Read published recipe hashes from this URL')
            command.add_argument('--commit', default=capture('git', '-C', ROOT, 'rev-parse', 'HEAD').strip())
            command.add_argument('--build-release', type=int, required=True)
        elif name == 'reuse':
            command.add_argument('--previous', type=Path, required=True)
            command.add_argument('--artifacts', type=Path, required=True)
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
