"""Exercise the accepted-candidate interface without a GitHub or signing credential."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPORT = load('transaction-artifacts')
ARTIFACTS = load('package-artifacts')
SHA = 'a' * 40
TREE = 'b' * 40
ARCHES = ('x86_64', 'aarch64')


def candidate_fixture(root, binary=None, source=None, baseline=None, tree=TREE):
    pool = root / 'pool'
    bundle = pool / 'source-w0-probe'
    (bundle / 'src').mkdir(parents=True)
    srpm = bundle / 'src' / (source.name if source else 'probe-1-1.src.rpm')
    srpm.write_bytes(source.read_bytes() if source else b'shared source')
    profile = bundle / 'test-profile.yaml'
    profile.write_text('repositories: []\n')
    ARTIFACTS.write_json(bundle / 'manifest.json', {
        'schema': 2, 'package': 'probe', 'rpmx': (ROOT / '.rpmx-revision').read_text().strip(),
        'sources': [{'file': srpm.name, 'sha256': ARTIFACTS.digest(srpm)}],
        'targets': dict.fromkeys(ARCHES, {}), 'test_profile': ARTIFACTS.digest(profile),
        'has_tests': dict.fromkeys(ARCHES, True),
    })
    identity = (subprocess.check_output(['rpm', '-qp', '--qf', '%{NAME}\n%{EPOCHNUM}\n%{VERSION}\n%{RELEASE}', str(binary)], text=True).splitlines()
                if binary else ['probe', '0', '1', '1'])
    targets = {}
    for arch in ARCHES:
        accepted = pool / f'accepted-probe-{arch}' / 'probe' / arch
        accepted.mkdir(parents=True)
        rpm = accepted / (binary.name if binary else f'probe-1-1.{arch}.rpm')
        rpm.write_bytes(binary.read_bytes() if binary else arch.encode())
        ARTIFACTS.write_json(accepted / 'source-manifest.json', {
            'schema': 1, 'package': 'probe', 'arch': arch, 'source_manifest': ARTIFACTS.digest(bundle / 'manifest.json'),
            'binaries': {rpm.name: ARTIFACTS.digest(rpm)}, 'acceptance': 'passed', 'acceptance_repository': arch,
        })
        targets[arch] = {'rpms': [{'file': rpm.name, 'name': identity[0], 'evr': identity[1:], 'sha256': ARTIFACTS.digest(rpm), 'source': 'publish-fixture' if binary else 'probe'}]}
    state = root / 'state.json'
    ARTIFACTS.write_json(state, {
        'schema': 1, 'commit': SHA, 'tree': tree, 'pending': [], 'arches': list(ARCHES),
        'repositories': dict(zip(ARCHES, ARCHES)), 'builds': {'probe': {'wave': 0, 'targets': targets}},
        'catalog': {'probe': {'hash': 'recipe'}}, 'published': {}, 'build_release': 100, 'wave': 1,
        'baseline': baseline or dict.fromkeys(ARCHES, []),
    })
    candidate = root / 'candidate'
    EXPORT.pack(argparse.Namespace(state=state, artifacts=pool, output=candidate))
    return candidate


class AcceptedCandidate(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.candidate = candidate_fixture(self.root)

    def rewrite(self, path, change):
        value = json.loads(path.read_text())
        change(value)
        ARTIFACTS.write_json(path, value)
        # Recompute the inventory to test semantic checks independently of checksums.
        manifest = json.loads((self.candidate / 'candidate.json').read_text())
        manifest['files'][path.relative_to(self.candidate).as_posix()] = ARTIFACTS.digest(path)
        ARTIFACTS.write_json(self.candidate / 'candidate.json', manifest)

    def test_exact_accepted_candidate_passes(self):
        state = EXPORT.verify_candidate(self.candidate, TREE, SHA)
        self.assertEqual(state['pending'], [])

    def test_rebase_keeps_tree_identity_but_unrelated_tree_or_producer_is_rejected(self):
        EXPORT.verify_candidate(self.candidate, TREE, SHA)
        for tree, sha in [('c' * 40, SHA), (TREE, 'c' * 40)]:
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                EXPORT.verify_candidate(self.candidate, tree, sha)

    def test_changed_bytes_and_uninventoried_files_are_rejected(self):
        rpm = next((self.candidate / 'packages/probe/x86_64').glob('*.rpm'))
        original = rpm.read_bytes()
        rpm.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            EXPORT.verify_candidate(self.candidate, TREE)
        rpm.write_bytes(original)
        (self.candidate / 'extra.rpm').write_bytes(b'not accepted')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            EXPORT.verify_candidate(self.candidate, TREE)

    def test_another_acceptance_repository_and_failed_tests_are_rejected(self):
        receipt = self.candidate / 'packages/probe/aarch64/source-manifest.json'
        self.rewrite(receipt, lambda data: data.update(acceptance_repository='another repository'))
        with self.assertRaisesRegex(ValueError, 'acceptance or binary identity differs'):
            EXPORT.verify_candidate(self.candidate, TREE)
        self.rewrite(receipt, lambda data: data.update(acceptance_repository='aarch64', acceptance='failed'))
        with self.assertRaisesRegex(ValueError, 'acceptance did not pass'):
            EXPORT.verify_candidate(self.candidate, TREE)

    def test_source_target_cannot_omit_an_architecture(self):
        manifest = self.candidate / 'packages/probe/manifest.json'
        self.rewrite(manifest, lambda data: data['targets'].pop('aarch64'))
        with self.assertRaisesRegex(ValueError, 'source targets differ'):
            EXPORT.verify_candidate(self.candidate, TREE)


if __name__ == '__main__':
    unittest.main()
