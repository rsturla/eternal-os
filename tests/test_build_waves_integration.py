"""Real RPMs and roots. Opt in with RUN_RPM_INTEGRATION=1; no build mocks."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/build-waves'
PACKAGES = ['wave-a', 'wave-b', 'wave-c', 'wave-d']


def load(project, name):
    spec = importlib.util.spec_from_file_location(name, project / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(project, *arguments, success=True):
    """Keep command evidence even when a native build or assertion fails."""
    arguments = list(map(str, arguments))
    with (project / 'commands.log').open('a') as log:
        log.write(json.dumps(arguments) + '\n')
        log.flush()
        result = subprocess.run(arguments, cwd=project, stdout=log, stderr=log, timeout=1800)
    if success and result.returncode:
        raise AssertionError((project / 'commands.log').read_text()[-12000:])
    return result


@unittest.skipUnless(os.environ.get('RUN_RPM_INTEGRATION') == '1', 'set RUN_RPM_INTEGRATION=1 for real RPM builds')
class BuildWavesIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arch = platform.machine()
        if cls.arch not in ('x86_64', 'aarch64'):
            raise RuntimeError('native x86_64 or aarch64 host required')
        cls.rpmx = os.environ.get('RPMX', 'rpmx')
        for tool in (cls.rpmx, 'rpm', 'rpm2archive', 'podman', 'bwrap', 'createrepo_c', 'mergerepo_c', 'modifyrepo_c', 'git'):
            if not shutil.which(tool):
                raise RuntimeError(f'integration test requires {tool}')
        output = os.environ.get('RPM_WAVE_TEST_OUTPUT')
        if output:
            cls.root = Path(output).resolve()
            cls.root.mkdir(parents=True, exist_ok=True)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='rpm-wave-test-')
            cls.addClassCleanup(temporary.cleanup)
            cls.root = Path(temporary.name)
        cls.cache = cls.root / 'cache/cas'
        cls.empty = cls.root / 'empty'
        (cls.empty / 'pool').mkdir(parents=True)
        (cls.empty / 'rolling' / cls.arch).mkdir(parents=True)
        project = cls.project('baseline')
        command(project, 'createrepo_c', '--outputdir', cls.empty / 'rolling' / cls.arch, cls.empty / 'pool')
        cls.initialise(project, cls.empty, PACKAGES, release=100)
        waves = load(project, 'build-waves')
        planner = load(project, 'build-transaction')
        state = project / '.work/transaction/state.json'
        artifacts = project / '.work/artifacts'
        # Seed the published baseline through the real shared-SRPM build path.
        for package in PACKAGES:
            if json.loads(state.read_text())['pending'] != [package]:
                raise AssertionError('baseline dependency order changed')
            waves.LocalExecutor(artifacts, cls.cache, cls.rpmx).build_wave(state)
            planner.advance(argparse.Namespace(state=state, artifacts=artifacts, final=False))
        cls.published = cls.root / 'published'
        planner.view(argparse.Namespace(state=state, artifacts=artifacts, output=cls.published / 'rolling'))
        cls.baseline = json.loads(state.read_text())
        cls.baseline_project = project

    @classmethod
    def project(cls, name):
        project = cls.root / name
        project.mkdir()
        shutil.copytree(ROOT / 'scripts', project / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / '.rpmx-revision', project)
        (project / '.gitignore').write_text('.work/\ncommands.log\n__pycache__/\n')
        (project / 'rpmx-defaults.yaml').write_text('schema: 1\npackage:\n  source-date-epoch: 1704067200\n')
        (project / 'rebuild-policy.yaml').write_text('{}\n')
        (project / 'rebuild-requirements.yaml').write_text('schema: 1\nrequirements: []\n')
        profile = yaml.safe_load((FIXTURE / 'profile.yaml').read_text())
        profile['archs'] = [cls.arch]
        (project / 'profiles').mkdir()
        for filename in ('bootstrap.profile.yaml', 'eternal.profile.yaml'):
            (project / 'profiles' / filename).write_text(yaml.safe_dump(profile, sort_keys=False))
        for index, package in enumerate(PACKAGES):
            letter = package[-1]
            parent = project / 'packages' / package
            (parent / 'files').mkdir(parents=True)
            shutil.copy2(FIXTURE / 'main.c', parent / 'files')
            marker = ('#define INPUT_MARKER "old"\n' if index == 0 else
                      f'#include <{PACKAGES[index - 1]}.h>\n#define INPUT_MARKER WAVE_{PACKAGES[index - 1][-1].upper()}\n')
            (parent / 'files/marker.h').write_text(marker)
            shutil.copy2(ROOT / 'LICENSE', parent / 'files/LICENSE')
            pipeline = f'''install -d "$STAGE/usr/bin" "$STAGE/usr/include" "$STAGE/usr/lib64" "$STAGE/usr/share/licenses/{package}"
gcc -static -DSUFFIX='"/{letter}"' main.c -o "$STAGE/usr/bin/{package}"
gcc -c -DSUFFIX='"/{letter}"' main.c -o marker.o
ar rcsU "$STAGE/usr/lib64/lib{package}.a" marker.o
marker=$("$STAGE/usr/bin/{package}")
printf '#define WAVE_{letter.upper()} "%s"\\n' "$marker" > "$STAGE/usr/include/{package}.h"
install -m 0644 LICENSE "$STAGE/usr/share/licenses/{package}/LICENSE"
'''
            expected = 'new/' + '/'.join('abcd'[:index + 1])
            recipe = {
                'schema': 2,
                'package': {'name': package, 'version': '1', 'release': 1,
                            'summary': 'Dependency wave fixture', 'license': 'MIT'},
                'context': 'files',
                'build': {'root': {'profile': '../../profiles/bootstrap.profile.yaml'},
                          'packages': ['gcc', 'glibc-static', *([PACKAGES[index - 1]] if index else [])],
                          'pipeline': [{'runs': pipeline}]},
                'outputs': [{'name': package, 'lint': {'allow': ['static-archive']},
                             'files': {'license': [f'/usr/share/licenses/{package}/LICENSE']},
                             'tests': [{'name': 'installed-marker', 'script': f'test "$(/usr/bin/{package})" = "{expected}"'}]}],
            }
            (parent / 'package.yaml').write_text(yaml.safe_dump(recipe, sort_keys=False))
        command(project, 'git', 'init', '--quiet')
        command(project, 'git', 'add', '.')
        command(project, 'git', '-c', 'user.name=RPM wave test', '-c', 'user.email=wave-test@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'tests: seed fixture')
        return project

    @classmethod
    def initialise(cls, project, published, selected, release=200):
        command(project, 'git', 'add', '.')
        command(project, 'git', '-c', 'user.name=RPM wave test', '-c', 'user.email=wave-test@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'tests: freeze fixture inputs')
        command(project, 'python3', 'scripts/build-transaction.py', 'init', '--arch', cls.arch,
                '--state', '.work/transaction/state.json', '--base-url', published.as_uri(),
                '--packages', json.dumps(selected), '--build-release', release)

    def scenario(self, name, *, change=True):
        project = self.project(name)
        if change:
            (project / 'packages/wave-a/files/marker.h').write_text('#define INPUT_MARKER "new"\n')
        self.initialise(project, self.published, ['wave-a'])
        return project

    def build(self, project, *, maximum=8, success=True):
        return command(project, 'python3', 'scripts/build-waves.py', '--state', '.work/transaction/state.json',
                       '--artifacts', '.work/artifacts', '--output', '.work/candidate', '--cache', self.cache,
                       '--rpmx', self.rpmx, '--max-waves', maximum, success=success)

    def test_four_waves_use_exact_previous_rpms_and_accept_the_final_repository(self):
        project = self.scenario('four-waves')
        self.build(project)
        state = json.loads((project / '.work/transaction/state.json').read_text())
        self.assertEqual(state['wave'], 4)
        self.assertEqual(state['pending'], [])
        self.assertEqual({name: data['wave'] for name, data in state['builds'].items()}, dict(zip(PACKAGES, range(4))))
        for index, package in enumerate(PACKAGES):
            with self.subTest(package=package):
                bundle = project / f'.work/artifacts/source-w{index}-{package}'
                lock = yaml.safe_load((bundle / f'locks/root-{self.arch}.lock.json').read_text())
                locked = [entry for entries in lock['packages'].values() for entry in entries]
                if index:
                    provider = PACKAGES[index - 1]
                    dependency, = [entry for entry in locked if entry['name'] == provider]
                    rpm, = state['builds'][provider]['targets'][self.arch]['rpms']
                    algorithm, expected = dependency['checksum'].split(':', 1)
                    self.assertEqual(expected, rpm[algorithm])
                    self.assertNotEqual(rpm['sha256'], self.baseline['builds'][provider]['targets'][self.arch]['rpms'][0]['sha256'])
                accepted = project / f'.work/artifacts/accepted-{package}-{self.arch}/{package}/{self.arch}'
                record = json.loads((accepted / 'source-manifest.json').read_text())
                self.assertEqual(record['acceptance'], 'passed')
                self.assertEqual(record['acceptance_repository'], state['repositories'][self.arch])
                report = json.loads((accepted / 'acceptance/results.json').read_text())
                self.assertEqual(report['outcome'], 'passed')
                self.assertEqual(len(report['tests']), 1)
        # D's installed test asserts the literal new/a/b/c/d, independently of
        # the planner's interface records. Every candidate byte is inventoried.
        candidate = project / '.work/candidate'
        manifest = json.loads((candidate / 'candidate.json').read_text())
        for name, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((candidate / name).read_bytes()).hexdigest(), expected)

        # A new commit changes only D. Keep A/B/C's exact source records and
        # binaries, rebuild D, then accept all four against the new repository.
        before = state
        source = project / 'packages/wave-d/files/main.c'
        source.write_text(source.read_text().replace('puts(INPUT_MARKER SUFFIX)', 'puts(INPUT_MARKER SUFFIX "!")'))
        recipe = project / 'packages/wave-d/package.yaml'
        recipe.write_text(recipe.read_text().replace('new/a/b/c/d', 'new/a/b/c/d!'))
        command(project, 'git', 'add', '.')
        command(project, 'git', '-c', 'user.name=RPM wave test', '-c', 'user.email=wave-test@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'wave-d: change installed marker')
        reused = project / '.work/reused-artifacts'
        reused.mkdir()
        for path in (project / '.work/artifacts').iterdir():
            if path.name.startswith(('source-w', 'binary-w')):
                shutil.copytree(path, reused / path.name)
        state_path = project / '.work/reused/state.json'
        command(project, 'python3', 'scripts/build-transaction.py', 'reuse', '--previous',
                '.work/transaction/state.json', '--state', state_path, '--artifacts', reused, '--build-release', '300')
        planned = json.loads(state_path.read_text())
        self.assertEqual(planned['pending'], ['wave-d'])
        self.assertEqual(planned['reused_from']['packages'], PACKAGES[:3])
        command(project, 'python3', 'scripts/build-waves.py', '--state', state_path, '--artifacts', reused,
                '--output', '.work/reused-candidate', '--cache', self.cache, '--rpmx', self.rpmx)
        after = json.loads(state_path.read_text())
        self.assertNotEqual(after['commit'], before['commit'])
        self.assertEqual(after['builds']['wave-d']['wave'], 4)
        for package in PACKAGES[:3]:
            self.assertEqual(after['builds'][package], before['builds'][package])
        for package in PACKAGES:
            report = json.loads((reused / f'accepted-{package}-{self.arch}/{package}/{self.arch}/acceptance/results.json').read_text())
            self.assertEqual(report['outcome'], 'passed')

    def test_fresh_binary_worker_needs_only_the_bundle_and_input_archive(self):
        project = self.scenario('offline-worker')
        waves = load(project, 'build-waves')
        planner = load(project, 'build-transaction')
        state = project / '.work/transaction/state.json'
        artifacts = project / '.work/artifacts'
        waves.LocalExecutor(artifacts, self.cache, self.rpmx).build_wave(state)
        planner.advance(argparse.Namespace(state=state, artifacts=artifacts, final=False))
        prepared = project / '.work/prepared-b'
        command(project, 'python3', 'scripts/package-artifacts.py', 'prepare', '--package', 'wave-b',
                '--output', prepared, '--transaction', state, '--candidates', artifacts,
                '--cache', self.cache, '--rpmx', self.rpmx)
        manifest = json.loads((prepared / 'bundle/manifest.json').read_text())
        shutil.rmtree(manifest['repository_path'])
        state.rename(project / '.work/saved-state.json')
        artifacts.rename(project / '.work/saved-artifacts')
        # This worker has no assembled roots, RPM cache, repository snapshot,
        # candidate artifacts, or access to the coordinator's transaction file.
        command(project, 'python3', 'scripts/package-artifacts.py', 'rebuild',
                '--bundle', prepared / 'bundle', '--inputs', prepared / 'inputs', '--arch', self.arch,
                '--output', project / '.work/offline-output', '--cache', project / '.work/fresh-cache/cas',
                '--transaction', prepared / 'bundle/transaction.json', '--rpmx', self.rpmx)
        output = project / f'.work/offline-output/wave-b/{self.arch}'
        rpm, = output.glob('*.rpm')
        self.assertTrue(rpm.is_file())
        record = json.loads((output / 'source-manifest.json').read_text())
        self.assertIn('wave-a', record['consumed'])

    def test_release_only_rebuild_stops_without_consumers(self):
        project = self.scenario('unchanged', change=False)
        waves = load(project, 'build-waves')
        planner = load(project, 'build-transaction')
        state = project / '.work/transaction/state.json'
        artifacts = project / '.work/artifacts'
        waves.LocalExecutor(artifacts, self.cache, self.rpmx).build_wave(state)
        planner.advance(argparse.Namespace(state=state, artifacts=artifacts, final=False))
        result = json.loads(state.read_text())
        self.assertEqual(result['pending'], [])
        self.assertEqual(set(result['builds']), {'wave-a'})
        self.assertNotEqual(result['builds']['wave-a']['targets'][self.arch]['rpms'][0]['sha256'],
                            self.baseline['builds']['wave-a']['targets'][self.arch]['rpms'][0]['sha256'])
        self.assertEqual(result['interfaces']['wave-a'], result['baseline_interfaces']['wave-a'])

    def test_failed_wave_prevents_dependents_acceptance_and_export(self):
        project = self.project('failed-build')
        (project / 'packages/wave-a/files/marker.h').write_text('#define INPUT_MARKER "new"\n')
        recipe = project / 'packages/wave-b/package.yaml'
        data = yaml.safe_load(recipe.read_text())
        data['build']['pipeline'][0]['runs'] = 'exit 42\n'
        recipe.write_text(yaml.safe_dump(data, sort_keys=False))
        self.initialise(project, self.published, ['wave-a'])
        self.assertNotEqual(self.build(project, success=False).returncode, 0)
        state = json.loads((project / '.work/transaction/state.json').read_text())
        self.assertEqual(state['pending'], ['wave-b'])
        self.assertEqual(set(state['builds']), {'wave-a'})
        report = json.loads((project / f'.work/artifacts/binary-w1-wave-b-{self.arch}/wave-b/{self.arch}/run-report.json').read_text())
        self.assertEqual(report['primary']['code'], 'RPMX-SANDBOX-002')
        self.assertIn('42', report['primary']['message'])
        self.assertFalse(list((project / '.work/artifacts').glob('source-w*-wave-c')))
        self.assertFalse((project / '.work/artifacts/acceptance-repository').exists())
        self.assertFalse((project / '.work/candidate').exists())

    def test_failed_acceptance_prevents_export(self):
        project = self.project('failed-acceptance')
        # The old baseline builds successfully. Its installed tests require
        # the new marker, so these exact old RPMs must fail acceptance.
        shutil.copytree(self.baseline_project / '.work', project / '.work')
        self.assertNotEqual(self.build(project, success=False).returncode, 0)
        self.assertTrue((project / '.work/artifacts/acceptance-repository').is_dir())
        accepted = project / f'.work/artifacts/accepted-wave-a-{self.arch}/wave-a/{self.arch}'
        report = json.loads((accepted / 'acceptance/results.json').read_text())
        self.assertNotEqual(report['outcome'], 'passed')
        test, = report['tests']
        self.assertEqual(test['name'], 'installed-marker')
        self.assertEqual(test['status'], 'failed')
        self.assertEqual(test['primary']['code'], 'RPMX-TEST-003')
        self.assertFalse((project / '.work/candidate').exists())

    def test_unsettled_cycle_fails_at_the_wave_limit(self):
        project = self.project('cycle')
        recipe = project / 'packages/wave-a/package.yaml'
        data = yaml.safe_load(recipe.read_text())
        data['build']['packages'].append('wave-b')
        recipe.write_text(yaml.safe_dump(data, sort_keys=False))
        (recipe.parent / 'files/marker.h').write_text('#include <wave-b.h>\n#define INPUT_MARKER WAVE_B\n')
        self.initialise(project, self.published, ['wave-a'])
        self.assertNotEqual(self.build(project, maximum=2, success=False).returncode, 0)
        self.assertIn('rebuild closure did not settle', (project / 'commands.log').read_text())
        self.assertFalse((project / '.work/artifacts/acceptance-repository').exists())
        self.assertFalse((project / '.work/candidate').exists())


if __name__ == '__main__':
    unittest.main()
