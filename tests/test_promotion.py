"""Check merged-tree reuse, artifact provenance, and envelope-only signing."""

import argparse
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROMOTE = load('promote-packages')
SIGN = load('sign-packages')
ARTIFACTS = load('package-artifacts')
TRANSPORT = load('transaction-artifacts')
HEAD, MERGED, BASE, TREE, TESTED = (letter * 40 for letter in 'abcde')


def inputs():
    baseline = {arch: [{'name': 'lib', 'checksum': 'one'}] for arch in PROMOTE.ARCHES}
    state = {'catalog': {'probe': {'hash': 'new'}, 'kept': {'hash': 'same'}},
             'builds': {'probe': {}}, 'baseline': copy.deepcopy(baseline), 'build_release': 200, 'wave': 2}
    published = {'hashes': {'probe': 'old', 'kept': 'same'}, 'build_release': 100}
    return {'tree': TREE}, state, {'probe': 'new', 'kept': 'same'}, baseline, published


class MergeInputs(unittest.TestCase):
    def check(self, receipt, state, hashes, baseline, published):
        return PROMOTE.check_inputs(receipt, state, MERGED, TREE, hashes, baseline, published)

    def test_rebase_or_squash_commit_can_reuse_identical_tested_tree(self):
        receipt, state, hashes, baseline, published = inputs()
        result = self.check(receipt, state, hashes, baseline, published)
        self.assertEqual(result, {'schema': 1, 'commit': MERGED, 'hashes': hashes, 'build_release': 202})

    def test_changed_tree_baseline_inputs_or_missing_failed_release_package_rebuild(self):
        for change, message in [('tree', 'source tree'), ('baseline', 'baseline changed'),
                                ('hash', 'build inputs'), ('coverage', 'all required'), ('counter', 'older')]:
            with self.subTest(change=change):
                receipt, state, hashes, baseline, published = copy.deepcopy(inputs())
                if change == 'tree':
                    receipt['tree'] = 'another tree'
                elif change == 'baseline':
                    baseline['x86_64'] = [{'name': 'lib', 'checksum': 'two'}]
                elif change == 'hash':
                    hashes['probe'] = 'another source input'
                elif change == 'coverage':
                    published['hashes']['kept'] = 'earlier failed version'
                else:
                    published['build_release'] = 300
                with self.assertRaisesRegex(ValueError, message):
                    self.check(receipt, state, hashes, baseline, published)

    def test_baseline_record_order_is_irrelevant(self):
        receipt, state, hashes, baseline, published = copy.deepcopy(inputs())
        for arch in PROMOTE.ARCHES:
            state['baseline'][arch] = [{'name': 'other', 'checksum': 'two'}, *state['baseline'][arch]]
            baseline[arch] = list(reversed(state['baseline'][arch]))
        self.check(receipt, state, hashes, baseline, published)


class Discovery(unittest.TestCase):
    def fixture(self):
        pr = {'number': 81, 'merged': True, 'merge_commit_sha': MERGED,
              'base': {'ref': 'main', 'repo': {'full_name': 'owner/repo'}},
              'head': {'sha': HEAD, 'repo': {'id': 1}}}
        run = {'id': 20, 'run_attempt': 1, 'event': 'pull_request', 'status': 'completed',
               'conclusion': 'success', 'head_sha': HEAD, 'path': '.github/workflows/ci.yml',
               'head_repository': {'id': 1}, 'pull_requests': [
                   {'number': 81, 'head': {'sha': HEAD}, 'base': {'sha': BASE}}]}
        artifact = {'id': 30, 'name': 'release-candidate', 'expired': False, 'digest': 'sha256:' + '1' * 64}
        return pr, run, artifact

    def discover(self, pr, run, artifact):
        def api(path):
            if '/commits/' in path:
                return [{'number': 81}]
            if '/pulls/81' in path:
                return pr
            if '/workflows/' in path:
                return {'workflow_runs': [run]}
            if '/artifacts' in path:
                return {'artifacts': [artifact]}
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as temporary, patch.object(PROMOTE, 'api', side_effect=api), \
                patch.object(PROMOTE, 'git', return_value=TREE):
            path = Path(temporary) / 'attempt.json'
            result = PROMOTE.find(argparse.Namespace(repository='owner/repo', commit=MERGED, output=path))
            return result, json.loads(path.read_text()) if path.exists() else None

    def test_successful_associated_pr_run_is_bound_to_its_artifact(self):
        result, attempt = self.discover(*self.fixture())
        self.assertTrue(result['found'])
        self.assertEqual((attempt['run'], attempt['artifact']['id'], attempt['head']), (20, 30, HEAD))

    def test_successful_merge_queue_head_is_preferred_and_bound_to_its_tree(self):
        _, run, artifact = self.fixture()
        run.update(event='merge_group', head_branch='gh-readonly-queue/main/pr-81-a',
                   head_repository={'full_name': 'owner/repo'}, pull_requests=[])
        def api(path):
            if '/workflows/' in path:
                return {'workflow_runs': [run]}
            if '/git/commits/' in path:
                return {'tree': {'sha': TREE}}
            if '/artifacts' in path:
                return {'artifacts': [artifact]}
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as temporary, patch.object(PROMOTE, 'api', side_effect=api), \
                patch.object(PROMOTE, 'git', return_value=TREE):
            path = Path(temporary) / 'attempt.json'
            result = PROMOTE.find(argparse.Namespace(repository='owner/repo', commit=MERGED, output=path))
            attempt = json.loads(path.read_text())
        self.assertEqual(result['event'], 'merge_group')
        self.assertEqual(attempt['head'], HEAD)
        self.assertIsNone(attempt['pr'])

    def test_failed_wrong_commit_push_other_workflow_and_expired_artifacts_are_ineligible(self):
        for change in ('failed', 'sha', 'push', 'workflow', 'association', 'expired', 'digest', 'merge'):
            with self.subTest(change=change):
                pr, run, artifact = self.fixture()
                if change == 'failed': run['conclusion'] = 'failure'
                elif change == 'sha': run['head_sha'] = 'wrong'
                elif change == 'push': run['event'] = 'push'
                elif change == 'workflow': run['path'] = '.github/workflows/other.yml'
                elif change == 'association': run['pull_requests'] = []
                elif change == 'expired': artifact['expired'] = True
                elif change == 'digest': artifact.pop('digest')
                else: pr['merge_commit_sha'] = HEAD
                self.assertFalse(self.discover(pr, run, artifact)[0]['found'])


class ArchiveSafety(unittest.TestCase):
    def test_traversal_links_and_duplicate_paths_are_rejected(self):
        for name, mode, duplicate in [('../outside', 0, False), ('/outside', 0, False),
                                      ('link', 0o120777, False), ('file', 0, True)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / 'candidate.zip'
                with zipfile.ZipFile(archive, 'w') as stream:
                    member = zipfile.ZipInfo(name)
                    member.external_attr = mode << 16
                    stream.writestr(member, 'bytes')
                    if duplicate:
                        stream.writestr(name, 'other bytes')
                with self.assertRaises(ValueError):
                    PROMOTE.unpack(archive, root / 'out')
                self.assertFalse((root / 'outside').exists())


@unittest.skipUnless(shutil.which('rpmx'), 'rpmx required')
class CandidateIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.fixture = Path(cls.temporary.name)
        stage = cls.fixture / 'stage'
        (stage / 'opt').mkdir(parents=True)
        (stage / 'opt/probe').write_text('tested payload\n')
        recipe = cls.fixture / 'package.yaml'
        recipe.write_text("schema: 2\npackage:\n  name: probe\n  version: '1'\n  release: 1\n  summary: Promotion fixture\n  license: MIT\noutputs:\n  - name: probe\n    arch: noarch\n")
        def run(*args):
            subprocess.run([str(arg) for arg in args], check=True, capture_output=True)
        run('rpmx', 'build', recipe, '--stage', stage, '--arch', 'x86_64', '--output', cls.fixture / 'binary',
            '--no-tests', '--no-lint', '--no-index')
        (cls.fixture / 'source').mkdir()
        run('rpmx', 'srpm', recipe, '--sources', cls.fixture / 'source', '--output', cls.fixture / 'sources')
        run('rpmx', 'keygen', '--bits', '2048', '--output', cls.fixture / 'key.asc')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def candidate(self):
        members = self.root / 'members'
        bundle = members / 'source-w0-probe'
        (bundle / 'src').mkdir(parents=True)
        source = next((self.fixture / 'sources').glob('*.src.rpm'))
        binary = next((self.fixture / 'binary').rglob('*.rpm'))
        shutil.copy2(source, bundle / 'src' / source.name)
        (bundle / 'test-profile.yaml').write_text('repositories: []\n')
        ARTIFACTS.write_json(bundle / 'manifest.json', {
            'schema': 1, 'package': 'probe', 'rpmx': (ROOT / '.rpmx-revision').read_text().strip(),
            'sources': [{'file': source.name, 'sha256': ARTIFACTS.digest(source)}],
            'targets': {arch: {} for arch in PROMOTE.ARCHES}, 'recipe_hash': 'new',
            'test_profile': ARTIFACTS.digest(bundle / 'test-profile.yaml'),
            'has_tests': {arch: False for arch in PROMOTE.ARCHES},
        })
        state = {'schema': 1, 'commit': TESTED, 'tree': TREE, 'pending': [], 'wave': 1,
                 'catalog': {'probe': {'hash': 'new'}}, 'published': {'hashes': {}},
                 'baseline': {arch: [{'name': 'lib', 'checksum': 'one'}] for arch in PROMOTE.ARCHES},
                 'build_release': 200, 'repositories': {arch: 'repository-' + arch for arch in PROMOTE.ARCHES},
                 'builds': {'probe': {'wave': 0, 'targets': {arch: {'rpms': [
                     {'file': binary.name, 'sha256': ARTIFACTS.digest(binary)}]} for arch in PROMOTE.ARCHES}}}}
        for arch in PROMOTE.ARCHES:
            directory = members / ('accepted-probe-' + arch) / 'probe' / arch
            directory.mkdir(parents=True)
            shutil.copy2(binary, directory / binary.name)
            ARTIFACTS.write_json(directory / 'source-manifest.json', {
                'schema': 1, 'package': 'probe', 'arch': arch, 'acceptance': 'not-required',
                'acceptance_repository': state['repositories'][arch],
                'source_manifest': ARTIFACTS.digest(bundle / 'manifest.json'),
                'binaries': {binary.name: ARTIFACTS.digest(binary)},
            })
        ARTIFACTS.write_json(self.root / 'state.json', state)
        candidate = self.root / 'candidate'
        TRANSPORT.pack(argparse.Namespace(state=self.root / 'state.json', artifacts=members, output=candidate))
        return candidate, state

    def test_pack_and_verify_real_source_and_binary_artifacts(self):
        candidate, _ = self.candidate()
        _, state = PROMOTE.validate_inventory(candidate)
        self.assertEqual(set(state['builds']), {'probe'})
        binary = next((candidate / 'packages/probe/x86_64').glob('*.rpm'))
        binary.write_bytes(binary.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            PROMOTE.validate_inventory(candidate)

    def test_self_consistent_inventory_cannot_add_an_untested_rpm(self):
        candidate, _ = self.candidate()
        extra = candidate / 'packages/probe/extra/untested.src.rpm'
        extra.parent.mkdir()
        extra.write_bytes(b'not tested')
        path = candidate / 'candidate.json'
        receipt = json.loads(path.read_text())
        receipt['files'][extra.relative_to(candidate).as_posix()] = ARTIFACTS.digest(extra)
        ARTIFACTS.write_json(path, receipt)
        with self.assertRaisesRegex(ValueError, 'noncanonical'):
            PROMOTE.validate_inventory(candidate)

    def test_missing_acceptance_and_source_mixups_cannot_be_packed(self):
        candidate, _ = self.candidate()
        members = self.root / 'members'
        path = members / 'accepted-probe-aarch64/probe/aarch64/source-manifest.json'
        record = json.loads(path.read_text())
        for change in ({'acceptance': 'pending'}, {'source_manifest': 'different source'}):
            ARTIFACTS.write_json(path, dict(record, **change))
            with self.assertRaises(ValueError):
                TRANSPORT.pack(argparse.Namespace(state=self.root / 'state.json', artifacts=members,
                                                 output=self.root / ('bad-' + next(iter(change)))))

    def test_signing_changes_envelopes_but_keeps_every_tested_content_byte(self):
        candidate, _ = self.candidate()
        packages = candidate / 'packages'
        before = {path.relative_to(packages).as_posix(): (SIGN.digest(path), SIGN.content_digest(path))
                  for path in packages.rglob('*.rpm')}
        SIGN.sign(packages, self.fixture / 'key.asc')
        receipt = json.loads((packages / 'signing.json').read_text())['rpms']
        self.assertEqual(set(receipt), set(before))
        for path, (original, content) in before.items():
            self.assertEqual(SIGN.content_digest(packages / path), content)
            self.assertNotEqual(SIGN.digest(packages / path), original)
            self.assertEqual(receipt[path]['tested_sha256'], original)
            self.assertEqual(receipt[path]['signed_sha256'], SIGN.digest(packages / path))

    def test_signer_that_changes_a_payload_is_rejected(self):
        directory = self.root / 'tampered'
        directory.mkdir()
        original = next((self.fixture / 'binary').rglob('*.rpm'))
        target = directory / original.name
        shutil.copy2(original, target)
        def corrupt(*args, **kwargs):
            target.write_bytes(target.read_bytes() + b'changed payload')
        with patch.object(SIGN.subprocess, 'run', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'changed a tested'):
                SIGN.sign(directory, self.fixture / 'key.asc')
        self.assertFalse((directory / 'signing.json').exists())

    def test_verified_github_archive_and_current_inputs_prepare_main_publication_without_rebuild(self):
        candidate, state = self.candidate()
        archive = self.root / 'download.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            for path in candidate.rglob('*'):
                if path.is_file():
                    package.write(path, path.relative_to(candidate).as_posix())
        artifact = {'id': 30, 'expired': False, 'digest': 'sha256:' + ARTIFACTS.digest(archive)}
        attempt = {'repository': 'owner/repo', 'commit': MERGED, 'head': HEAD, 'base': BASE,
                   'run': 20, 'run_attempt': 1, 'artifact': artifact, 'pr': 81}
        ARTIFACTS.write_json(self.root / 'attempt.json', attempt)
        def api(path):
            if '/actions/runs/' in path:
                return {'status': 'completed', 'conclusion': 'success',
                        'head_sha': attempt['head'], 'event': attempt.get('event', 'pull_request'), 'run_attempt': 1}
            if '/actions/artifacts/' in path:
                return artifact
            return {'sha': TESTED, 'tree': {'sha': TREE}, 'parents': [{'sha': BASE}, {'sha': HEAD}]}
        def run(command, **options):
            if command[0] == 'gh':
                options['stdout'].write(archive.read_bytes())
            elif command[0] != 'git':
                raise AssertionError(command)
        class Baseline:
            run = staticmethod(lambda *args: None)
            baseline_packages = staticmethod(lambda directory: state['baseline'][directory.name])
        actual_load = PROMOTE.load
        def load(name):
            return Baseline if name == 'build-transaction' else actual_load(name)
        args = argparse.Namespace(attempt=self.root / 'attempt.json', commit=MERGED,
                                  base_url='https://example.invalid', output=self.root / 'ready')
        with patch.object(PROMOTE, 'api', side_effect=api), patch.object(PROMOTE, 'load', side_effect=load), \
                patch.object(PROMOTE, 'git', side_effect=lambda *args: TREE if args[-1] == 'HEAD^{tree}' else MERGED), \
                patch.object(PROMOTE.subprocess, 'run', side_effect=run), \
                patch.object(PROMOTE.subprocess, 'check_output', return_value='probe new\n'), \
                patch.object(PROMOTE.urllib.request, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(b'{"hashes":{"probe":"old"},"build_release":100}')):
            result = PROMOTE.verify(args)
            attempt.update(event='merge_group', head=TESTED, pr=None)
            ARTIFACTS.write_json(args.attempt, attempt)
            queued = argparse.Namespace(**dict(vars(args), output=self.root / 'queue-ready'))
            self.assertTrue(PROMOTE.verify(queued)['eligible'])
            attempt['head'] = HEAD
            ARTIFACTS.write_json(args.attempt, attempt)
            with self.assertRaisesRegex(ValueError, 'not the PR head'):
                PROMOTE.verify(queued)
            archive.write_bytes(archive.read_bytes() + b'tampered archive')
            with self.assertRaisesRegex(ValueError, 'archive digest mismatch'):
                PROMOTE.verify(args)
        self.assertTrue(result['eligible'])
        self.assertEqual(json.loads((args.output / 'packages/build-state.json').read_text())['commit'], MERGED)
        self.assertEqual(json.loads((args.output / 'packages/promotion.json').read_text())['run'], 20)
        original = next((candidate / 'packages/probe/x86_64').glob('*.rpm'))
        reused = args.output / 'packages/probe/x86_64' / original.name
        self.assertEqual(reused.read_bytes(), original.read_bytes())


if __name__ == '__main__':
    unittest.main()
