"""Repair requirements use exact provider inputs, not runtime test outcomes."""

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROVENANCE = load('build-provenance')
TX = load('build-transaction')
QUEUE = load('queue-packages')
CAPABILITY = 'rpmx(component:crypto)'
REQUIREMENT = {'capability': CAPABILITY, 'minimum': '2'}


def receipt(version='1', complete=None):
    return {'schema': 1, 'roots_complete': True, 'inputs': [
        {'root': 'build', 'name': 'any-distribution-compiler', 'evr': '1.0-3',
         'checksum': 'sha256:old', 'provides': {CAPABILITY: version}}],
        'coverage': [] if complete is None else [{'root': 'build', 'checksum': 'sha256:old',
                                               'complete': complete, 'used': []}]}


class RepairRequirements(unittest.TestCase):
    def test_missing_legacy_unlocked_and_stale_inputs_require_rebuild(self):
        for value in (None, {'schema': 1, 'roots_complete': False}, receipt()):
            self.assertTrue(PROVENANCE.failures(value, [REQUIREMENT], 'x86_64'))
        self.assertFalse(PROVENANCE.failures(receipt('2'), [REQUIREMENT], 'x86_64'))

    def test_complete_component_coverage_can_exclude_unused_crypto(self):
        self.assertTrue(PROVENANCE.failures(receipt(complete=False), [REQUIREMENT], 'x86_64'))
        self.assertFalse(PROVENANCE.failures(receipt(complete=True), [REQUIREMENT], 'x86_64'))
        used = receipt(complete=True)
        used['coverage'][0]['used'] = [CAPABILITY]
        self.assertTrue(PROVENANCE.failures(used, [REQUIREMENT], 'x86_64'))

    def test_coverage_cannot_suppress_another_root_or_a_toolchain_requirement(self):
        value = receipt(complete=True)
        value['coverage'][0]['root'] = 'sysroot'
        self.assertTrue(PROVENANCE.failures(value, [REQUIREMENT], 'x86_64'))
        cap = 'rpmx(toolchain:example)'
        value['inputs'][0]['provides'] = {cap: '1'}
        self.assertTrue(PROVENANCE.failures(value, [{'capability': cap, 'minimum': '2'}], 'x86_64'))

    def test_repaired_upstream_version_does_not_hide_a_backport_revision_floor(self):
        requirement = {**REQUIREMENT, 'minimum_evr': '1.0-4'}
        self.assertTrue(PROVENANCE.failures(receipt('2'), [requirement], 'x86_64'))
        value = receipt('2')
        value['inputs'][0]['evr'] = '1.0-4'
        self.assertFalse(PROVENANCE.failures(value, [requirement], 'x86_64'))

    def test_requirements_are_arch_scoped_and_all_matching_inputs_must_be_fixed(self):
        requirement = {**REQUIREMENT, 'arches': ['aarch64']}
        self.assertFalse(PROVENANCE.failures(None, [requirement], 'x86_64'))
        value = receipt('2')
        value['inputs'].append(receipt()['inputs'][0])
        self.assertTrue(PROVENANCE.failures(value, [requirement], 'aarch64'))

    def test_rpm_version_comparison_preserves_epoch_tilde_and_caret(self):
        for first, second in [('1:1-1', '9-9'), ('2-4', '2-3'), ('1.0^git1', '1.0'), ('1.0', '1.0~rc1')]:
            self.assertGreater(PROVENANCE.compare(first, second), 0)
        self.assertEqual(PROVENANCE.compare('0:2-1', '2-1'), 0)
        # Macro-like text is data, including non-ASCII and quotes.
        self.assertEqual(PROVENANCE.compare('1%{error:bad}"é', '1%{error:bad}"é'), 0)

    def test_policy_schema_rejects_typos_and_unversioned_repairs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'rebuild-requirements.yaml'
            with patch.object(PROVENANCE, 'ROOT', root):
                for document in ('schema: 2\nrequirements: []', 'schema: 1\nrequirements: null',
                                 'schema: 1\nrequirements: [{capability: "rpmx(x)", minimum: 2}]',
                                 'schema: 1\nrequirements: [{capability: "rpmx(x)", minimum: "2", arch: x86_64}]'):
                    path.write_text(document)
                    with self.assertRaises(ValueError):
                        PROVENANCE.load()

    def test_provider_payload_changes_trigger_rebuilds_without_abi_changes(self):
        original = {'name': 'compiler', 'interface': {'provides': [], 'files': []},
                    'provider_capabilities': ['rpmx(toolchain:example) = 1'], 'payload': [['/usr/bin/cc', 'old']]}
        changed = copy.deepcopy(original)
        changed['payload'][0][1] = 'new'
        self.assertNotEqual(TX.fingerprint([original]), TX.fingerprint([changed]))
        changed = dict(original, sha256='signature-only-change')
        self.assertEqual(TX.fingerprint([original]), TX.fingerprint([changed]))

    def test_buildinput_capabilities_connect_consumers_to_portable_providers(self):
        arches = TX.ARCHES
        state = {'catalog': {name: {'targets': {arch: {'sources': [name], 'requires': [], 'provides': []}
                                                  for arch in arches}} for name in ['app', 'compiler']},
                 'baseline': {arch: [
                     {'source': 'app', 'provides': ['buildinput(component:crypto)'], 'requires': []},
                     {'source': 'compiler', 'provides': [CAPABILITY], 'requires': []}] for arch in arches},
                 'builds': {}, 'policy': {}}
        self.assertEqual(TX.dependencies(state, 'app', 'x86_64'), {'compiler'})
        state['baseline']['x86_64'][0]['provides'] = []
        self.assertEqual(TX.dependencies(state, 'app', 'x86_64'), set())

    def test_queue_rejects_a_new_repair_policy_even_with_unchanged_abi(self):
        with self.assertRaisesRegex(ValueError, 'repair requirements changed'):
            QUEUE.check_reuse({'builds': {}, 'requirements': []}, {'requirements': [REQUIREMENT]}, TX, Path('.'))

    def test_final_gate_rechecks_exact_bytes_not_saved_state_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            rpm = directory / 'app' / 'x86_64' / 'app.rpm'
            rpm.parent.mkdir(parents=True)
            rpm.write_bytes(b'candidate')
            state = {'builds': {'app': {'wave': 0, 'targets': {'x86_64': {'rpms': [
                {'file': rpm.name, 'sha256': TX.digest(rpm), 'source': 'app'}]}}}},
                     'baseline': {'x86_64': []}}
            with patch.object(TX, 'ARCHES', ['x86_64']), patch.object(TX.provenance, 'read', return_value=receipt()):
                with self.assertRaisesRegex(ValueError, 'below the repair requirement'):
                    TX.verify_repairs(state, directory, [REQUIREMENT])
                rpm.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'changed repair candidate'):
                    TX.verify_repairs(state, directory, [REQUIREMENT])

class RepairPlanning(unittest.TestCase):
    def test_policy_only_change_selects_stale_consumers_after_their_provider(self):
        import argparse
        import contextlib
        import io
        arches = TX.ARCHES
        recipes = {name: {'hash': name, 'targets': {arch: {'sources': [name], 'requires': [],
                            'provides': [CAPABILITY] if name == 'compiler' else ['app']}
                            for arch in arches}} for name in ['app', 'compiler']}
        baseline = [{'source': 'app', 'name': 'app', 'requires': [],
                     'provides': ['buildinput(component:crypto)'], 'checksum': 'sha256:abc'}]
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / 'state.json'
            (Path(temporary) / 'rebuild-policy.yaml').write_text('{}\n')
            args = argparse.Namespace(state=state_path, packages='["compiler"]', published=None,
                                      base_url='https://example.invalid', commit='a' * 40, build_release=1)
            with patch.object(TX, 'ROOT', Path(temporary)), patch.object(TX, 'catalog', return_value=recipes), patch.object(TX, 'run'), \
                    patch.object(TX, 'capture', return_value='tree'), patch.object(TX, 'baseline_packages', return_value=baseline), \
                    patch.object(TX, 'baseline_rpm', return_value=Path('app.rpm')), \
                    patch.object(TX.provenance, 'read', return_value=receipt()), \
                    patch.object(TX.provenance, 'load', return_value=[REQUIREMENT]), contextlib.redirect_stdout(io.StringIO()):
                TX.initialise(args)
            import json
            state = json.loads(state_path.read_text())
            self.assertEqual(set(state['requested']), {'app', 'compiler'})
            self.assertEqual(state['pending'], ['compiler'])
            self.assertIn('below the repair requirement', state['reasons']['app'][0])
            self.assertEqual(state['requirements'], [REQUIREMENT])

    def test_baseline_download_is_checksum_verified_before_a_receipt_is_used(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(TX, 'open_url', return_value=contextlib.closing(io.BytesIO(b'changed'))):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                TX.baseline_rpm({'checksum': 'sha256:' + '0' * 64, 'url': 'https://example.invalid/app.rpm'}, Path(temporary))


if __name__ == '__main__':
    unittest.main()
