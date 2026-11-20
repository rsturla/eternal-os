#!/usr/bin/env python3
"""Build a transaction in dependency order, then accept its final repository."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(name, operation, *arguments):
    subprocess.run([sys.executable, str(ROOT / 'scripts' / (name + '.py')), operation,
                    *map(str, arguments)], check=True)


class LocalExecutor:
    """Execution adapter. Both operations block until all work succeeds.

    build_wave reads an immutable state file and writes source/binary artifact
    directories. accept writes accepted artifacts against the sealed repository.
    A hosted adapter can dispatch workers and collect those same directories.
    Any failure raises; the coordinator must not advance or export afterwards.
    """

    def __init__(self, artifacts, cache, rpmx):
        self.artifacts, self.cache, self.rpmx = artifacts, cache, rpmx

    def build_wave(self, state_path):
        state = json.loads(state_path.read_text())
        planner = load('build-transaction')
        for package in state['pending']:
            prepared = self.artifacts / f'prepared-w{state["wave"]}-{package}'
            command('package-artifacts', 'prepare', '--package', package, '--output', prepared,
                    '--transaction', state_path, '--candidates', self.artifacts, '--cache', self.cache, '--rpmx', self.rpmx)
            bundle = self.artifacts / f'source-w{state["wave"]}-{package}'
            shutil.move(prepared / 'bundle', bundle)
            for arch in planner.architectures(state):
                command('package-artifacts', 'rebuild', '--bundle', bundle, '--inputs', prepared / 'inputs',
                        '--arch', arch, '--output', self.artifacts / f'binary-w{state["wave"]}-{package}-{arch}',
                        '--transaction', state_path, '--cache', self.cache, '--rpmx', self.rpmx)

    def accept(self, state_path, repository):
        state = json.loads(state_path.read_text())
        planner = load('build-transaction')
        for arch in planner.architectures(state):
            command('package-artifacts', 'accept-batch', '--state', state_path, '--artifacts', self.artifacts,
                    '--packages', json.dumps(sorted(state['builds'])), '--arch', arch,
                    '--repository', repository, '--output', self.artifacts)


def build(args, executor=None):
    planner = load('build-transaction')
    executor = executor or LocalExecutor(args.artifacts, args.cache, args.rpmx)
    if args.max_waves < 1:
        raise ValueError('max-waves must be positive')
    state = json.loads(args.state.read_text())
    if not state['pending'] and not state['builds']:
        return
    for iteration in range(args.max_waves):
        if not json.loads(args.state.read_text())['pending']:
            break
        executor.build_wave(args.state)
        planner.advance(argparse.Namespace(state=args.state, artifacts=args.artifacts,
                                           final=iteration == args.max_waves - 1, cache=args.cache))
    repository = args.artifacts / 'acceptance-repository'
    planner.seal(argparse.Namespace(state=args.state, artifacts=args.artifacts, output=repository))
    executor.accept(args.state, repository)
    # Publication is separate. Export bytes only after every acceptance passed.
    command('transaction-artifacts', 'pack', '--state', args.state, '--artifacts', args.artifacts, '--output', args.output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=Path.home() / '.cache/rpmx/cas')
    parser.add_argument('--rpmx', default=os.environ.get('RPMX', 'rpmx'))
    parser.add_argument('--max-waves', type=int, default=32)
    args = parser.parse_args()
    os.environ['RPMX'] = args.rpmx
    build(args)


if __name__ == '__main__':
    main()
