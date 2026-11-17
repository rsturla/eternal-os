#!/usr/bin/env python3
"""Check a PR's existing RPMs against the merge queue's current main baseline."""

import argparse
import contextlib
import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def queue_pr(repository, event, promote):
    group = event['merge_group']
    match = re.fullmatch(r'refs/heads/gh-readonly-queue/main/pr-(\d+)-[0-9a-f]+', group['head_ref'])
    if not match or group['base_ref'] != 'refs/heads/main':
        raise ValueError('expected a main merge-queue ref')
    prefix = f'repos/{repository}'
    if promote.git('rev-parse', 'HEAD') != group['head_sha']:
        raise ValueError('checkout differs from queue head')
    if promote.api(f'{prefix}/git/ref/heads/main')['object']['sha'] != group['base_sha']:
        raise ValueError('main advanced; requeue against latest main')
    pr = promote.api(f'{prefix}/pulls/{match[1]}')
    if (pr['state'] != 'open' or pr['base']['ref'] != 'main'
            or pr['base']['repo']['full_name'] != repository):
        raise ValueError('queue entry is not an open PR targeting this main branch')
    # Fork PR heads need not be reachable from local branches after checkout.
    promote.git('fetch', '--no-tags', 'origin', f'refs/pull/{pr["number"]}/head')
    if promote.git('rev-parse', 'FETCH_HEAD') != pr['head']['sha']:
        raise ValueError('PR head advanced; requeue the current PR')
    # Prove that the queue contains this one PR. A queue ref alone does not
    # prove group membership. Reject larger groups instead of omitting RPMs.
    tree = promote.git('merge-tree', '--write-tree', group['base_sha'], pr['head']['sha']).splitlines()[0]
    if tree != promote.git('rev-parse', 'HEAD^{tree}'):
        raise ValueError('queue tree is not latest main plus one PR; use queue build concurrency and group size 1')
    return pr


def records(state, package, arch):
    sources = state['catalog'][package]['targets'][arch]['sources']
    return sorted(json.dumps(item, sort_keys=True) for item in state['baseline'][arch] if item['source'] in sources)


def compare_evr(left, right):
    # Pass arbitrary RPM version strings as decimal-escaped Lua strings. This
    # avoids macro expansion and code injection in rpm's embedded Lua engine.
    def literal(value):
        return '"' + ''.join(f'\\{byte:03d}' for byte in str(value).encode()) + '"'
    for first, second in zip(left, right, strict=True):
        compared = int(subprocess.check_output([
            'rpm', '--eval', '%{lua:print(rpm.vercmp(' + literal(first) + ',' + literal(second) + '))}'], text=True))
        if compared:
            return compared
    return 0


def check_reuse(original, current, transaction, scratch):
    """Reject stale build inputs, while allowing unrelated main changes."""
    built = set(original['builds'])
    required = {name for name, data in current['catalog'].items()
                if current['published'].get('hashes', {}).get(name) != data['hash']}
    if required - built:
        raise ValueError(f'latest main has unpublished or uncovered recipes: {sorted(required - built)}; wait for publication or refresh PR CI')
    for package in built:
        if (package not in current['catalog'] or
                original['catalog'][package]['hash'] != current['catalog'][package]['hash']):
            raise ValueError(f'{package}: build inputs changed on main; update the PR and rebuild')
        for arch in transaction.ARCHES:
            # A newer baseline for the same family needs a fresh PR build.
            if records(original, package, arch) != records(current, package, arch):
                raise ValueError(f'{package}: published source family changed; update the PR and rebuild')
            for rpm in original['builds'][package]['targets'][arch]['rpms']:
                for published in current['baseline'][arch]:
                    if published['name'] == rpm['name'] and compare_evr(rpm['evr'], published['evr']) <= 0:
                        raise ValueError(f'{package}: PR RPM does not upgrade published {rpm["name"]}; update the PR and rebuild')
    state = copy.deepcopy(current)
    for key in ('builds', 'interfaces', 'baseline_interfaces', 'build_release', 'wave'):
        state[key] = copy.deepcopy(original[key])
    state['pending'] = []
    # Include dependencies from the exact old build roots as well as current
    # declarations and generated requirements. Compiler policy covers tools.
    for package in built:
        for arch in transaction.ARCHES:
            providers = transaction.dependencies(state, package, arch)
            providers.update(original['builds'][package]['targets'][arch]['consumed'])
            for provider in providers - built:
                if provider not in original['catalog'] or provider not in state['catalog']:
                    raise ValueError(f'{package}: build provider changed; update the PR and rebuild')
                if records(original, provider, arch) == records(state, provider, arch):
                    continue
                before = transaction.baseline_interface(original, provider, arch, scratch)
                after = transaction.baseline_interface(state, provider, arch, scratch)
                if before != after:
                    raise ValueError(f'{package}: {provider} changed public build inputs on {arch}; update the PR and rebuild')
    missing = transaction.next_packages(state)
    if missing:
        raise ValueError(f'latest main needs additional dependency rebuilds: {missing}; update the PR and rebuild')
    return state


def stage(candidate, state, output):
    """Copy verified PR bytes into the existing acceptance worker layout."""
    for package, build in state['builds'].items():
        source = candidate / 'packages' / package
        bundle = output / 'artifacts' / f'source-w{build["wave"]}-{package}'
        bundle.mkdir(parents=True)
        for name in ('manifest.json', 'test-profile.yaml'):
            shutil.copy2(source / name, bundle / name)
        shutil.copytree(source / 'src', bundle / 'src')
        for arch in state['baseline']:
            binary = output / 'artifacts' / f'binary-w{build["wave"]}-{package}-{arch}' / package / arch
            shutil.copytree(source / arch, binary)


def prepare(args):
    promote = load('promote-packages')
    transaction = load('build-transaction')
    event = json.loads(args.event.read_text())
    pr = queue_pr(args.repository, event, promote)
    group = event['merge_group']
    affected = json.loads(subprocess.check_output(
        [str(ROOT / 'scripts/affected.sh'), '--base', group['base_sha'], '--json'], text=True))
    if not affected:
        return {'matrix': [], 'packages': [], 'pr': pr['number'], 'run': None}
    attempt = promote.find_pr_attempt(args.repository, group['head_sha'], pr)
    with tempfile.TemporaryDirectory(prefix='eternal-queue-') as temporary:
        scratch = Path(temporary)
        candidate, receipt, original = promote.download_candidate(attempt, scratch)
        state_path = args.output / 'transaction' / 'state.json'
        with contextlib.redirect_stdout(sys.stderr):
            transaction.initialise(argparse.Namespace(state=state_path, packages='changed', published=args.base_url,
                                                     base_url=args.base_url, commit=group['head_sha'],
                                                     build_release=original['build_release']))
        current = json.loads(state_path.read_text())
        state = check_reuse(original, current, transaction, scratch)
        state['queue'] = {'base': group['base_sha'], 'pull_request': pr['number'], 'head': pr['head']['sha'],
                          'run': attempt['run'], 'run_attempt': attempt['run_attempt'],
                          'artifact': attempt['artifact']['id'], 'artifact_digest': attempt['artifact']['digest'],
                          'built_commit': receipt['commit'], 'built_tree': receipt['tree']}
        stage(candidate, state, args.output)
        transaction.write(state_path, state)
        transaction.seal(argparse.Namespace(state=state_path, artifacts=args.output / 'artifacts',
                                            output=args.output / 'repository'))
    matrix = [{'package': package, 'arch': arch, 'wave': build['wave'],
               'runner': 'ubuntu-26.04-arm' if arch == 'aarch64' else 'ubuntu-26.04'}
              for package, build in sorted(state['builds'].items()) for arch in transaction.ARCHES]
    return {'matrix': matrix, 'packages': sorted(state['builds']), 'pr': pr['number'], 'run': attempt['run']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--event', type=Path, required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Queue failures block merging. They must never silently start a new build.
    print(json.dumps(prepare(args), separators=(',', ':')))


if __name__ == '__main__':
    main()
