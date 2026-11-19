"""Check transaction artifacts and artifact integrity before publication."""

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


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

    def fetch_result(self, code=None, message='GET https://sources.invalid/source failed: connection reset'):
        diagnostics = [{'code': code, 'message': message, 'severity': 'error'}] if code else []
        return subprocess.CompletedProcess([], 4 if code else 0, json.dumps({'diagnostics': diagnostics}), '')

    def test_source_network_failures_retry_acquisition_with_backoff(self):
        with patch.object(artifacts.subprocess, 'run', side_effect=[
                self.fetch_result('RPMX-FETCH-003'), self.fetch_result('RPMX-FETCH-003'), self.fetch_result()]) as run, \
                patch.object(artifacts.time, 'sleep') as sleep:
            artifacts.fetch_sources('rpmx', self.root / 'package.yaml', self.root / 'cache')
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [15, 45])
        self.assertTrue(all(call.args[0][1] == 'fetch' for call in run.call_args_list))

    def test_source_retry_limit_and_permanent_failures(self):
        for code, message, attempts in [
                ('RPMX-FETCH-003', 'GET https://sources.invalid/source failed: timeout', 3),
                ('RPMX-FETCH-002', 'digest mismatch', 1),
                ('RPMX-FETCH-003', 'cannot create a staging file for response: disk full', 1),
                ('RPMX-FETCH-003', 'cannot read response: disk full', 1),
                ('RPMX-INCLUDE-001', 'invalid recipe', 1)]:
            with self.subTest(code=code, message=message), \
                    patch.object(artifacts.subprocess, 'run', return_value=self.fetch_result(code, message)) as run, \
                    patch.object(artifacts.time, 'sleep') as sleep:
                with self.assertRaises(subprocess.CalledProcessError):
                    artifacts.fetch_sources('rpmx', self.root / 'package.yaml', self.root / 'cache')
                self.assertEqual(run.call_count, attempts)
                self.assertEqual(sleep.call_count, attempts - 1)

    def test_unknown_source_failure_does_not_retry(self):
        result = subprocess.CompletedProcess([], 4, 'not a diagnostic report', '')
        with patch.object(artifacts.subprocess, 'run', return_value=result) as run, \
                patch.object(artifacts.time, 'sleep') as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                artifacts.fetch_sources('rpmx', self.root / 'package.yaml', self.root / 'cache')
        run.assert_called_once()
        sleep.assert_not_called()

    def test_pool_keeps_only_latest_canonical_bytes_and_rejects_tampering(self):
        pool = load('transaction-artifacts')
        directory = self.root / 'artifacts/binary-w2-example-x86_64/example/x86_64'
        directory.mkdir(parents=True)
        rpm = directory / 'example.rpm'
        rpm.write_bytes(b'latest candidate')
        checksum = artifacts.digest(rpm)
        (directory / 'source-manifest.json').write_text(json.dumps({
            'package': 'example', 'arch': 'x86_64', 'binaries': {rpm.name: checksum}}))
        (directory / 'evidence').mkdir()
        (directory / 'evidence/private.rpm').write_bytes(b'not a candidate')
        old = self.root / 'artifacts/binary-w1-example-x86_64/example/x86_64'
        old.mkdir(parents=True)
        (old / 'example.rpm').write_bytes(b'obsolete candidate')
        state = self.root / 'state.json'
        state.write_text(json.dumps({'arches': ['x86_64'], 'builds': {'example': {'wave': 2,
            'targets': {'x86_64': {'rpms': [{'file': rpm.name, 'sha256': checksum}]}}}}}))
        args = argparse.Namespace(state=state, artifacts=self.root / 'artifacts', output=self.root / 'pool')
        pool.pool(args)
        files = {path.relative_to(args.output).as_posix() for path in args.output.rglob('*') if path.is_file()}
        self.assertEqual(files, {'binary-w2-example-x86_64/example/x86_64/example.rpm',
                                 'binary-w2-example-x86_64/example/x86_64/source-manifest.json'})
        rpm.write_bytes(b'changed after advance')
        args.output = self.root / 'tampered-pool'
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            pool.pool(args)

    def test_seed_package_is_not_mistaken_for_a_same_named_candidate(self):
        path = self.root / 'bash.rpm'
        path.write_bytes(b'Fedora bash bytes')
        transaction = {
            'catalog': {'bash': {'targets': {'x86_64': {'sources': ['bash']}}}},
            'builds': {'bash': {'targets': {'x86_64': {'rpms': [
                {'name': 'bash', 'sha512': hashlib.sha512(b'Eternal bash bytes').hexdigest()}]}}}},
        }
        package = {'name': 'bash', 'srpm': 'bash-1-1.src.rpm',
                   'origin': {'kind': 'repository', 'repository': 'fedora'}}
        self.assertEqual(artifacts.consumed_providers(path, package, transaction, 'x86_64'), set())
        package['origin']['repository'] = 'eternal'
        with self.assertRaisesRegex(ValueError, 'obsolete candidate'):
            artifacts.consumed_providers(path, package, transaction, 'x86_64')
        path.write_bytes(b'Eternal bash bytes')
        self.assertEqual(artifacts.consumed_providers(path, package, transaction, 'x86_64'), {'bash'})

    def test_source_preparation_rejects_inputs_changed_after_planning(self):
        recipe = self.root / 'packages/probe/package.yaml'
        recipe.parent.mkdir(parents=True)
        recipe.write_text('build:\n  root:\n    profile: ../../profiles/build.yaml\n')
        profile = self.root / 'profiles/build.yaml'
        profile.parent.mkdir()
        profile.write_text('{}\n')
        transaction = self.root / 'state.json'
        transaction.write_text(json.dumps({'pending': ['probe'], 'catalog': {'probe': {'hash': 'planned'}}}))
        args = argparse.Namespace(package='probe', output=self.root / 'prepared', transaction=transaction)
        with patch.object(artifacts, 'ROOT', self.root), \
             patch.object(artifacts.subprocess, 'check_output', return_value='probe changed\n'), \
             patch.object(artifacts, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'recipe inputs differ from the transaction snapshot'):
                artifacts.prepare(args)
        run.assert_not_called()

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

    def test_sha256_locked_inputs_match_exact_sha512_transaction_candidates(self):
        content = b'the exact current transaction RPM'
        relative = 'sha256/' + hashlib.sha256(content).hexdigest()
        artifacts.import_inputs(self.archive(relative, content), self.root / 'cache')
        path = self.root / 'cache' / relative
        candidate = {'name': 'provider', 'sha512': hashlib.sha512(content).hexdigest()}
        artifacts.verify_candidate(path, candidate)
        stale = dict(candidate, sha512=hashlib.sha512(b'another RPM with the same name').hexdigest())
        with self.assertRaisesRegex(ValueError, 'obsolete candidate: provider'):
            artifacts.verify_candidate(path, stale)

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
