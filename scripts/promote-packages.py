#!/usr/bin/env python3
"""Reuse a merged PR's tested package set only when source and repository inputs match."""

import argparse
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHES = ('x86_64', 'aarch64')


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True))


def pages(path, field=None):
    page = 1
    while True:
        data = api(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
        values = data[field] if field else data
        yield from values
        if len(values) < 100:
            return
        page += 1


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def candidate_attempt(prefix, repository, commit, run, event, pr=None, base=None):
    artifacts = [item for item in pages(f'{prefix}/actions/runs/{run["id"]}/artifacts', 'artifacts')
                 if item['name'] == 'release-candidate' and not item['expired']]
    if len(artifacts) != 1 or not re.fullmatch(r'sha256:[0-9a-f]{64}', artifacts[0].get('digest', '')):
        return None
    return {'repository': repository, 'commit': commit, 'event': event, 'pr': pr,
            'head': run['head_sha'], 'base': base, 'run': run['id'],
            'run_attempt': run['run_attempt'], 'artifact': artifacts[0]}


def find_pr_attempt(repository, commit, pr):
    prefix = f'repos/{repository}'
    head = pr['head']['sha']
    for run in pages(f'{prefix}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={head}&status=success', 'workflow_runs'):
        association = next((item for item in run['pull_requests'] if item['number'] == pr['number']), None)
        if (run['event'] != 'pull_request' or run['status'] != 'completed' or run['conclusion'] != 'success'
                or run['head_sha'] != head or run['path'] != '.github/workflows/ci.yml' or not association
                or run['head_repository']['id'] != pr['head']['repo']['id']
                or association['head']['sha'] != head):
            continue
        attempt = candidate_attempt(prefix, repository, commit, run, 'pull_request',
                                    pr['number'], association['base']['sha'])
        if attempt:
            return attempt
    raise ValueError('no successful PR run with an unexpired matching candidate; rerun PR CI before queueing')


def find(args):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', args.repository) or not re.fullmatch(r'[0-9a-f]{40}', args.commit):
        raise ValueError('invalid repository or merged commit')
    prefix = f'repos/{args.repository}'
    tree = git('rev-parse', args.commit + '^{tree}')
    # Queue heads can contain several PRs and may acquire different commit SHAs
    # when rebased onto main. Bind the successful queue run to its exact tree.
    for run in pages(f'{prefix}/actions/workflows/ci.yml/runs?event=merge_group&status=success', 'workflow_runs'):
        if (run['event'] != 'merge_group' or run['status'] != 'completed' or run['conclusion'] != 'success'
                or run['path'] != '.github/workflows/ci.yml'
                or not run.get('head_branch', '').startswith('gh-readonly-queue/main/')
                or run['head_repository'].get('full_name') != args.repository):
            continue
        tested = api(f'{prefix}/git/commits/{run["head_sha"]}')
        if tested['tree']['sha'] != tree:
            continue
        attempt = candidate_attempt(prefix, args.repository, args.commit, run, 'merge_group')
        if attempt:
            write(args.output, attempt)
            return {'found': True, 'run': run['id'], 'event': 'merge_group'}
    for associated in pages(f'{prefix}/commits/{args.commit}/pulls'):
        pr = api(f'{prefix}/pulls/{associated["number"]}')
        if (not pr.get('merged') or pr.get('merge_commit_sha') != args.commit or
                pr['base']['ref'] != 'main' or pr['base']['repo']['full_name'] != args.repository):
            continue
        try:
            attempt = find_pr_attempt(args.repository, args.commit, pr)
        except ValueError:
            continue
        write(args.output, attempt)
        return {'found': True, 'run': attempt['run'], 'pr': pr['number'], 'event': 'pull_request'}
    return {'found': False, 'reason': 'no successful PR or queue run with an unexpired matching candidate'}


def unpack(archive, destination):
    with zipfile.ZipFile(archive) as package:
        seen = set()
        for member in package.infolist():
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (path.is_absolute() or '..' in path.parts or '\\' in member.filename or
                    not path.parts or member.filename in seen or
                    (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise ValueError(f'invalid candidate archive path: {member.filename}')
            seen.add(member.filename)
            output = destination.joinpath(*path.parts)
            if member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, output.open('xb') as stream:
                    shutil.copyfileobj(source, stream)


def validate_inventory(candidate):
    artifacts = load('package-artifacts')
    receipt = json.loads((candidate / 'candidate.json').read_text())
    if receipt['schema'] != 1 or receipt['rpmx'] != (ROOT / '.rpmx-revision').read_text().strip():
        raise ValueError('candidate format or rpmx revision differs')
    actual = {path.relative_to(candidate).as_posix() for path in candidate.rglob('*') if path.is_file()}
    if actual != set(receipt['files']) | {'candidate.json'}:
        raise ValueError('candidate inventory is incomplete or contains extra files')
    for relative, expected in receipt['files'].items():
        path = PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise ValueError('invalid candidate inventory path')
        artifacts.verify_file(candidate / relative, expected)
    state = json.loads((candidate / 'state.json').read_text())
    if state['pending'] or not state['builds'] or not state.get('repositories'):
        raise ValueError('candidate has no completed acceptance transaction')
    if state.get('tree') != receipt['tree'] or state['commit'] != receipt['commit']:
        raise ValueError('candidate source identity differs from transaction')
    if set(state['repositories']) != set(ARCHES):
        raise ValueError('candidate does not cover both architectures')
    packages = candidate / 'packages'
    expected = set(state['builds']) | {'build-state.json'}
    if {path.name for path in packages.iterdir()} != expected:
        raise ValueError('candidate package set differs from completed builds')
    for package, build in state['builds'].items():
        if Path(package).name != package or package in ('.', '..'):
            raise ValueError('invalid candidate package name')
        directory = packages / package
        if {path.name for path in directory.iterdir()} != {*ARCHES, 'src', 'manifest.json', 'test-profile.yaml'}:
            raise ValueError('noncanonical files in candidate package')
        source_record = artifacts.load_bundle(directory)
        if {path.name for path in (directory / 'src').iterdir()} != {source['file'] for source in source_record['sources']}:
            raise ValueError('unrecorded source package in candidate')
        if source_record['recipe_hash'] != state['catalog'][package]['hash']:
            raise ValueError('source artifact was prepared from different recipe inputs')
        for arch in ARCHES:
            record = json.loads((packages / package / arch / 'source-manifest.json').read_text())
            if record.get('acceptance_repository') != state['repositories'][arch]:
                raise ValueError('acceptance used another repository generation')
            expected_binaries = {rpm['file']: rpm['sha256'] for rpm in build['targets'][arch]['rpms']}
            if ({path.name for path in (directory / arch).iterdir()} != set(record['binaries']) | {'source-manifest.json'}
                    or any(name.endswith('.src.rpm') for name in record['binaries'])):
                raise ValueError('noncanonical files in accepted binary package')
            if record['binaries'] != expected_binaries:
                raise ValueError('accepted binary identities differ from the completed build')
        artifacts.verify(argparse.Namespace(bundle=packages / package, output=packages))
    return receipt, state


def check_inputs(receipt, state, commit, tree, hashes, baseline, published):
    if receipt['tree'] != tree:
        raise ValueError('merged source tree differs from the tested tree')
    if {name: item['hash'] for name, item in state['catalog'].items()} != hashes:
        raise ValueError('merged build inputs differ from the tested inputs')
    normal = lambda records: sorted(json.dumps(item, sort_keys=True) for item in records)
    if set(state['baseline']) != set(ARCHES) or any(
            normal(state['baseline'][arch]) != normal(baseline[arch]) for arch in ARCHES):
        raise ValueError('published dependency baseline changed')
    required = {name for name, value in hashes.items() if published.get('hashes', {}).get(name) != value}
    if required - state['builds'].keys():
        raise ValueError(f'PR did not build all required recipes: {sorted(required - state["builds"].keys())}')
    # Queue validation checks each output's EVR and unchanged source family.
    # Direct PR reuse retains the conservative global counter check.
    if not state.get('queue') and state['build_release'] <= published.get('build_release', 0):
        raise ValueError('PR release counter is older than the published transaction')
    return {'schema': 1, 'commit': commit,
            'hashes': dict(published.get('hashes', {}), **{name: hashes[name] for name in state['builds']}),
            'build_release': max(state['build_release'] + state['wave'], published.get('build_release', 0))}


def download_candidate(attempt, scratch):
    """Verify the service archive, completed run and source commit before use."""
    prefix = f'repos/{attempt["repository"]}'
    # Recheck the run, attempt, and immutable artifact identity before download.
    run = api(f'{prefix}/actions/runs/{attempt["run"]}')
    artifact = api(f'{prefix}/actions/artifacts/{attempt["artifact"]["id"]}')
    if (run['status'] != 'completed' or run['conclusion'] != 'success' or run['event'] != attempt.get('event', 'pull_request')
            or run['head_sha'] != attempt['head'] or run['run_attempt'] != attempt['run_attempt']
            or artifact['expired'] or artifact['digest'] != attempt['artifact']['digest']):
        raise ValueError('PR evidence expired or changed')
    archive = scratch / 'candidate.zip'
    with archive.open('wb') as stream:
        subprocess.run(['gh', 'api', f'{prefix}/actions/artifacts/{artifact["id"]}/zip'], stdout=stream, check=True)
    data = load('package-artifacts')
    if 'sha256:' + data.digest(archive) != artifact['digest']:
        raise ValueError('GitHub artifact archive digest mismatch')
    candidate = scratch / 'candidate'
    unpack(archive, candidate)
    receipt, state = validate_inventory(candidate)
    if state.get('queue') and attempt.get('event') != 'merge_group':
        raise ValueError('queue validation evidence requires a successful queue run')
    tested = api(f'{prefix}/git/commits/{state["commit"]}')
    parents = [parent['sha'] for parent in tested['parents']]
    matches_run = (state['commit'] == attempt['head'] if attempt.get('event') == 'merge_group' else
                   state['commit'] == attempt['head'] or parents == [attempt['base'], attempt['head']])
    if tested['sha'] != state['commit'] or tested['tree']['sha'] != receipt['tree'] or not matches_run:
        raise ValueError('candidate commit is not the PR head or its tested merge tree')
    return candidate, receipt, state


def verify(args):
    attempt = json.loads(args.attempt.read_text())
    if attempt['commit'] != args.commit or git('rev-parse', 'HEAD') != args.commit:
        raise ValueError('release checkout differs from requested merge')
    with tempfile.TemporaryDirectory(prefix='eternal-promotion-') as temporary:
        scratch = Path(temporary)
        candidate, receipt, state = download_candidate(attempt, scratch)
        hashes = dict(line.split() for line in subprocess.check_output(
            [str(ROOT / 'scripts/package-hash.sh')], text=True).splitlines())
        transaction = load('build-transaction')
        baseline = {}
        for arch in ARCHES:
            directory = scratch / 'baseline' / arch
            transaction.run('mergerepo_c', '--repo', args.base_url.rstrip('/') + '/rolling/' + arch,
                            '--outputdir', directory, '--no-database', '--nogroups', '--noupdateinfo', '--compress-type=gz')
            baseline[arch] = transaction.baseline_packages(directory)
        published = {'hashes': {}}
        try:
            request = urllib.request.Request(args.base_url.rstrip('/') + '/build-state.json', headers={'User-Agent': 'eternal-package-builder/1'})
            with urllib.request.urlopen(request, timeout=60) as response:
                published = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        if published.get('commit'):
            subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', published['commit'], args.commit], check=True)
        published_state = check_inputs(receipt, state, args.commit, git('rev-parse', 'HEAD^{tree}'), hashes, baseline, published)
        shutil.copytree(candidate / 'packages', args.output / 'packages')
        write(args.output / 'packages/build-state.json', published_state)
        write(args.output / 'packages/promotion.json', {
            'schema': 1, 'repository': attempt['repository'], 'event': attempt.get('event', 'pull_request'),
            'pull_request': attempt['pr'],
            'run': attempt['run'], 'run_attempt': attempt['run_attempt'], 'artifact': attempt['artifact']['id'],
            'artifact_digest': attempt['artifact']['digest'], 'tested_commit': state['commit'], 'merged_commit': args.commit,
            'queue': state.get('queue'),
            'tree': receipt['tree'],
        })
    return {'eligible': True, 'run': attempt['run'], 'pr': attempt['pr']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    find_parser = commands.add_parser('find')
    find_parser.add_argument('--repository', required=True)
    verify_parser = commands.add_parser('verify')
    verify_parser.add_argument('--attempt', type=Path, required=True)
    verify_parser.add_argument('--base-url', required=True)
    for command in (find_parser, verify_parser):
        command.add_argument('--commit', required=True)
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = find(args) if args.operation == 'find' else verify(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        # Failed eligibility is a normal rebuild path. Publication failures are
        # handled by the publisher and must never enter this fallback.
        print(f'PR reuse unavailable: {error}', file=sys.stderr)
        result = {'found' if args.operation == 'find' else 'eligible': False, 'reason': str(error)}
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
