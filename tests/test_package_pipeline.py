"""Check transaction artifacts and artifact integrity before publication."""

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


artifacts = load('package-artifacts')


class ArtifactTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def archive(self, name, content):
        path = self.root / 'inputs.tar.gz'
        with tarfile.open(path, 'w:gz') as tar:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
        return path

    def test_target_inputs_require_valid_payload_checksums(self):
        content = b'pinned dependency RPM'
        name = 'sha512/' + hashlib.sha512(content).hexdigest()
        archive = self.archive(name, content)
        artifacts.import_inputs(archive, self.root / 'cache')
        self.assertEqual((self.root / 'cache' / name).read_bytes(), content)
        archive = self.archive(name, b'changed payload')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            artifacts.import_inputs(archive, self.root / 'cache')
        self.assertEqual((self.root / 'cache' / name).read_bytes(), content)

    def test_target_inputs_reject_archive_paths(self):
        archive = self.archive('../escape', b'payload')
        with self.assertRaisesRegex(ValueError, 'invalid dependency archive'):
            artifacts.import_inputs(archive, self.root / 'cache')
        self.assertFalse((self.root / 'escape').exists())

    def bundle(self):
        bundle = self.root / 'bundle'
        (bundle / 'src').mkdir(parents=True)
        source = bundle / 'src/probe-1-1.src.rpm'
        source.write_bytes(b'one shared source RPM')
        profile = bundle / 'test-profile.yaml'
        profile.write_text('profile')
        artifacts.write_json(bundle / 'manifest.json', {
            'schema': 1, 'package': 'probe', 'rpmx': (ROOT / '.rpmx-revision').read_text().strip(),
            'sources': [{'file': source.name, 'sha256': artifacts.digest(source)}],
            'targets': {arch: {} for arch in ('x86_64', 'aarch64')},
            'test_profile': artifacts.digest(profile), 'has_tests': {'x86_64': True, 'aarch64': True},
        })
        for arch in ('x86_64', 'aarch64'):
            output = self.root / 'out/probe' / arch
            output.mkdir(parents=True)
            binary = output / f'probe-1-1.{arch}.rpm'
            binary.write_bytes(arch.encode())
            artifacts.write_json(output / 'source-manifest.json', {
                'schema': 1, 'package': 'probe', 'arch': arch,
                'source_manifest': artifacts.digest(bundle / 'manifest.json'),
                'binaries': {binary.name: artifacts.digest(binary)}, 'acceptance': 'passed',
            })
        return argparse.Namespace(bundle=bundle, output=self.root / 'out')

    def test_transaction_verification_requires_all_architectures_and_the_same_source(self):
        args = self.bundle()
        artifacts.verify(args)
        self.assertTrue((self.root / 'out/probe/src/probe-1-1.src.rpm').is_file())
        record = self.root / 'out/probe/aarch64/source-manifest.json'
        original = json.loads(record.read_text())
        changed = dict(original, source_manifest='another source RPM')
        artifacts.write_json(record, changed)
        with self.assertRaisesRegex(ValueError, 'build source differs'):
            artifacts.verify(args)
        artifacts.write_json(record, dict(original, acceptance='failed'))
        with self.assertRaisesRegex(ValueError, 'acceptance did not pass'):
            artifacts.verify(args)
        record.unlink()
        with self.assertRaises(FileNotFoundError):
            artifacts.verify(args)

    def test_changed_rpm_bytes_fail_transaction_verification(self):
        args = self.bundle()
        binary = next((self.root / 'out/probe/x86_64').glob('*.rpm'))
        binary.write_bytes(b'changed after testing')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            artifacts.verify(args)
