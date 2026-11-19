#!/usr/bin/env python3
"""GitHub transport for immutable transaction snapshots and wave artifacts.

Dependency decisions and RPM validation belong to build-transaction.py and
package-artifacts.py. This adapter only moves their files, dispatches workers,
and reports the transaction status on its source commit.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile


def api(path, body=None, binary=False):
    command = ['gh', 'api', '-H', 'X-GitHub-Api-Version: 2026-03-10',
               f'repos/{os.environ["GITHUB_REPOSITORY"]}/{path}']
    if body is not None:
        command += ['--method', 'POST', '--input', '-']
    result = subprocess.check_output(command, input=json.dumps(body).encode() if body is not None else None)
    return result if binary else json.loads(result or b'null')


def download(run, name, destination, indexes=None):
    """Verify the archive digest and reject paths outside its destination."""
    indexes = {} if indexes is None else indexes
    run = int(run)
    if run not in indexes:
        indexes[run] = []
        page = 1
        while True:
            batch = api(f'actions/runs/{run}/artifacts?per_page=100&page={page}')['artifacts']
            indexes[run].extend(batch)
            if len(batch) < 100:
                break
            page += 1
    matches = [item for item in indexes[run] if item['name'] == name and not item['expired']]
    if len(matches) != 1:
        raise ValueError(f'expected one live artifact {name} in run {run}')
    record = matches[0]
    archive = api(f'actions/artifacts/{record["id"]}/zip', binary=True)
    if record.get('digest') != 'sha256:' + hashlib.sha256(archive).hexdigest():
        raise ValueError(f'artifact archive checksum mismatch: {name}')
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        for entry in source.infolist():
            target = (destination / entry.filename).resolve()
            if (not target.is_relative_to(destination.resolve()) or
                    stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError(f'unsafe artifact path: {entry.filename}')
        source.extractall(destination)


def read(directory):
    return (json.loads((directory / 'state.json').read_text()),
            json.loads((directory / 'context.json').read_text()))


def save(directory, context):
    (directory / 'context.json').write_text(json.dumps(context, sort_keys=True, indent=2) + '\n')


def outputs(values):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        for name, value in values.items():
            encoded = value if isinstance(value, str) else json.dumps(value, separators=(',', ':'))
            if '\n' in encoded or '\r' in encoded:
                raise ValueError('workflow outputs must fit on one line')
            stream.write(f'{name}={encoded}\n')


def initialise(args):
    state = json.loads((args.transaction / 'state.json').read_text())
    context = {'root_run': int(os.environ['GITHUB_RUN_ID']), 'runs': {},
               'source_ref': args.ref.removeprefix('refs/heads/'), 'source_sha': state['commit'], 'pr_number': args.pr_number}
    previous = getattr(args, 'previous_context', None)
    if previous:
        context['runs'] = json.loads(previous.read_text())['runs']
    save(args.transaction, context)
    status(state['commit'], 'pending', 'Building the RPM dependency closure')
    describe(args)


def restore(args):
    """Find transport artifacts; the shared planner decides what is reusable."""
    if args.output.exists() or args.artifacts.exists():
        raise ValueError('reuse destinations must be new directories')
    if args.run:
        runs = [api(f'actions/runs/{args.run}')]
    elif args.previous_sha:
        if not re.fullmatch('[0-9a-f]{40}', args.previous_sha):
            raise ValueError('invalid previous commit SHA')
        runs = api(f'actions/runs?head_sha={args.previous_sha}&status=success&per_page=100')['workflow_runs']
    else:
        runs = []
    if not args.run and getattr(args, 'base', None):
        base_sha = subprocess.check_output(['git', 'rev-parse', args.base], text=True).strip()
        for pull in api(f'commits/{base_sha}/pulls'):
            sha = pull['head']['sha']
            runs.extend(api(f'actions/workflows/ci.yml/runs?head_sha={sha}&status=success&per_page=100')['workflow_runs'])
    for run in runs:
        if run['status'] != 'completed' or run['conclusion'] != 'success':
            continue
        indexes = {run['id']: []}
        page = 1
        while True:
            batch = api(f'actions/runs/{run["id"]}/artifacts?per_page=100&page={page}')['artifacts']
            indexes[run['id']].extend(batch)
            if len(batch) < 100:
                break
            page += 1
        names = {item['name'] for item in indexes[run['id']] if not item['expired']}
        snapshots = [(int(name.removeprefix('transaction-w')), name) for name in names
                     if re.fullmatch(r'transaction-w[0-9]+', name)]
        if not snapshots or 'candidate-pool' not in names:
            continue
        _, name = max(snapshots)
        with tempfile.TemporaryDirectory(prefix='eternal-reuse-') as temporary:
            source = Path(temporary) / 'transaction'
            download(run['id'], name, source, indexes)
            state, context = read(source)
            same_pr = (context['source_ref'].removeprefix('refs/heads/') == args.ref.removeprefix('refs/heads/')
                       and context.get('pr_number') == args.pr_number)
            base = getattr(args, 'base', None)
            merged_base = base and state.get('tree') == subprocess.check_output(
                ['git', 'rev-parse', f'{base}^{{tree}}'], text=True).strip()
            if (state['commit'] != run['head_sha'] or context['source_sha'] != state['commit']
                    or not (same_pr or merged_base)):
                if args.run:
                    raise ValueError('reused artifacts belong to another source or pull request')
                continue
            if state['pending']:
                if args.run:
                    raise ValueError('requested reuse transaction has not settled')
                continue
            shutil.copytree(source, args.output)
        subprocess.run(['git', 'fetch', '--no-tags', 'origin', state['commit']], check=True)
        download(run['id'], 'candidate-pool', args.artifacts, indexes)
        outputs({'restored': True})
        return
    if args.run:
        raise ValueError('requested run has no complete candidate snapshot')
    outputs({'restored': False})


def candidate(args):
    """Locate successful CI evidence for exactly the target tree, including rebases."""
    target = api(f'commits/{args.commit}')['commit']['tree']['sha']
    if args.run:
        runs = [api(f'actions/runs/{args.run}')]
        sources = None
    else:
        pulls = ([api(f'pulls/{args.pr_number}')] if args.pr_number
                 else api(f'commits/{args.commit}/pulls'))
        sources = {pull['head']['sha'] for pull in pulls}
        sources.add(args.commit)
        runs = []
        for sha in sorted(sources):
            runs.extend(api(f'actions/workflows/ci.yml/runs?head_sha={sha}&status=success&per_page=100')['workflow_runs'])
    for run in sorted(runs, key=lambda run: run['id'], reverse=True):
        if (run['status'] != 'completed' or run['conclusion'] != 'success'
                or run['path'] != '.github/workflows/ci.yml'
                or run['repository']['full_name'] != os.environ['GITHUB_REPOSITORY']
                or (sources is not None and run['head_sha'] not in sources)):
            continue
        if api(f'commits/{run["head_sha"]}')['commit']['tree']['sha'] != target:
            continue
        artifacts = api(f'actions/runs/{run["id"]}/artifacts?name=release-candidate&per_page=100')['artifacts']
        if any(item['name'] == 'release-candidate' and not item['expired'] for item in artifacts):
            outputs({'run': run['id'], 'source_sha': run['head_sha'], 'skip': False})
            return
    # A successful empty transaction needs no repository publication.
    if not args.run:
        for sha in sorted(sources):
            if api(f'commits/{sha}')['commit']['tree']['sha'] != target:
                continue
            statuses = api(f'commits/{sha}/status')['statuses']
            latest = next((status for status in statuses if status['context'] == 'RPM transaction'), None)
            if latest and latest['state'] == 'success' and latest['description'] == 'No RPM changes':
                outputs({'skip': True})
                return
    raise ValueError('no accepted candidate matches the target tree; refresh PR CI before release')


def freshness(args):
    """Require the PR source to contain the current base before its RPMs can land."""
    subprocess.run(['git', 'merge-base', '--is-ancestor', args.base, args.commit], check=True)
    if args.pr_number:
        candidate(args)


def import_pr(args):
    """Mirror explicitly reviewed fork code into a branch with dispatch permission."""
    pull = api(f'pulls/{args.number}')
    if pull['state'] != 'open' or pull['base']['repo']['full_name'] != os.environ['GITHUB_REPOSITORY']:
        raise ValueError('pull request must be open and target this repository')
    head = pull['head']
    if head['sha'] != args.sha:
        raise ValueError('pull request moved since review; supply its reviewed SHA')
    if not re.fullmatch('[0-9a-f]{40}', args.sha):
        raise ValueError('invalid reviewed commit SHA')
    # Creating a ref never checks out or runs code from the fork.
    branch = f'codex/reviewed-pr-{args.number}-{args.sha[:12]}'
    api('git/refs', {'ref': 'refs/heads/' + branch, 'sha': args.sha})
    print(f'Reviewed branch: {branch}\nStart: gh workflow run ci.yml --ref {branch} -f pr_number={args.number}')


def describe(args):
    state, context = read(args.transaction)
    checkout = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    if checkout != state['commit'] or context['source_sha'] != state['commit']:
        raise ValueError('worker checkout differs from the transaction source commit')
    packages = sorted(state['builds'])
    matrix = [{'packages': packages[start:start + 4], 'batch': start // 4, 'arch': arch,
               'runner': 'ubuntu-26.04-arm' if arch == 'aarch64' else 'ubuntu-26.04'}
              for arch in state['arches'] for start in range(0, len(packages), 4)]
    outputs({'packages': state['pending'], 'arches': state['arches'], 'wave': state['wave'],
             'matrix': {'include': matrix},
             'empty': not state['pending'] and not state['builds']})


def sources(args):
    state, context = read(args.transaction)
    indexes = {}
    for package, build in state['builds'].items():
        wave = build['wave']
        run = context['runs'][str(wave)]
        name = f'source-w{wave}-{package}'
        download(run, name, args.artifacts / name, indexes=indexes)


def record(args):
    state, context = read(args.transaction)
    # advance has succeeded; its preceding generation was built in this run.
    context['runs'][str(state['wave'] - 1)] = int(os.environ['GITHUB_RUN_ID'])
    save(args.transaction, context)
    describe(args)


def status(sha, result, description, url=None):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('invalid commit SHA')
    api(f'statuses/{sha}', {'state': result, 'context': 'RPM transaction',
                          'description': description,
                          'target_url': url or f'{os.environ["GITHUB_SERVER_URL"]}/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'})


def dispatch(args):
    state, context = read(args.transaction)
    if not state['pending'] and not state['builds']:
        status(state['commit'], 'success', 'No RPM changes')
        return
    # A moving branch must not dispatch workers from a newer source tree.
    remote = subprocess.check_output(['git', 'ls-remote', 'origin', context['source_ref']], text=True).split()
    if len(remote) != 2 or remote[0] != state['commit']:
        raise ValueError('source ref moved; start a transaction for the new commit')
    response = api('actions/workflows/ci.yml/dispatches', {
        'ref': context['source_ref'],
        'inputs': {'phase': 'build' if state['pending'] else 'accept',
                   'snapshot_run': os.environ['GITHUB_RUN_ID'], 'wave': str(state['wave']),
                   'source_sha': state['commit'], 'pr_number': str(context.get('pr_number') or '')}})
    if not response or not response.get('workflow_run_id'):
        raise ValueError('GitHub did not return the dispatched workflow run')
    status(state['commit'], 'pending', f'RPM {"build" if state["pending"] else "acceptance"} wave {state["wave"]}',
           url=response['html_url'])
    print(response['html_url'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for name, function in [('restore', restore), ('init', initialise), ('describe', describe), ('sources', sources),
                           ('record', record), ('dispatch', dispatch)]:
        command = commands.add_parser(name)
        command.add_argument('--transaction', type=Path, default=Path('.work/transaction'))
        command.set_defaults(function=function)
        if name == 'init':
            command.add_argument('--ref', required=True)
            command.add_argument('--pr-number', type=int)
            command.add_argument('--previous-context', type=Path)
        if name == 'restore':
            command.add_argument('--run', type=int)
            command.add_argument('--previous-sha')
            command.add_argument('--ref', required=True)
            command.add_argument('--pr-number', type=int)
            command.add_argument('--base', help='Allow a settled candidate with the exact merged base tree')
            command.add_argument('--output', type=Path, default=Path('.work/previous'))
            command.add_argument('--artifacts', type=Path, default=Path('.work/candidates'))
        if name == 'sources':
            command.add_argument('--artifacts', type=Path, default=Path('.work/candidates'))
    command = commands.add_parser('candidate')
    command.add_argument('--commit', required=True)
    command.add_argument('--run', type=int)
    command.add_argument('--pr-number', type=int)
    command.set_defaults(function=candidate)
    command = commands.add_parser('freshness')
    command.add_argument('--commit', required=True)
    command.add_argument('--base', required=True)
    command.add_argument('--pr-number', type=int)
    command.set_defaults(function=freshness, run=None)
    command = commands.add_parser('import-pr')
    command.add_argument('--number', type=int, required=True)
    command.add_argument('--sha', required=True, help='Exact fork head SHA that a maintainer reviewed')
    command.set_defaults(function=import_pr)
    command = commands.add_parser('status')
    command.add_argument('--sha', required=True)
    command.add_argument('--result', choices=['success', 'failure'], required=True)
    command.set_defaults(function=lambda args: status(args.sha, args.result,
                         'RPM closure and acceptance passed' if args.result == 'success' else 'RPM transaction failed'))
    args = parser.parse_args()
    args.function(args)


if __name__ == '__main__':
    main()
