"""Exercise rebuild closure through the same state interface used by workers."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('transaction', ROOT / 'scripts/build-transaction.py')
TX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TX)


def fixture():
    catalog = {}
    baseline = {arch: [] for arch in TX.ARCHES}
    for name, requires in [('x', []), ('y', ['x-devel']), ('z', ['y-devel']), ('unrelated', [])]:
        catalog[name] = {'targets': {arch: {'sources': [name], 'provides': [name, name + '-devel'],
                                          'requires': requires} for arch in TX.ARCHES}}
    return {'catalog': catalog, 'baseline': baseline, 'builds': {}, 'interfaces': {},
            'baseline_interfaces': {}, 'policy': {}}


def built(state, name, fingerprint, view=None):
    state['baseline_interfaces'][name] = {arch: 'old-' + name for arch in TX.ARCHES}
    state['interfaces'][name] = {arch: fingerprint for arch in TX.ARCHES}
    state['builds'][name] = {'view': copy.deepcopy(view or {}), 'targets': {
        arch: {'requires': [], 'provides': [name + '-devel'], 'consumed': []} for arch in TX.ARCHES}}


class RebuildClosure(unittest.TestCase):
    def test_abi_change_selects_consumers_but_not_unrelated_recipes(self):
        state = fixture()
        built(state, 'x', 'new-x')
        self.assertEqual(set(TX.next_packages(state)), {'y'})

    def test_consumer_built_in_same_wave_is_rebuilt_against_new_provider(self):
        state = fixture()
        built(state, 'x', 'new-x')
        built(state, 'y', 'old-y')
        self.assertEqual(set(TX.next_packages(state)), {'y'})
        state['builds']['y']['view'] = copy.deepcopy(state['interfaces'])
        self.assertEqual(TX.next_packages(state), {})

    def test_follow_on_abi_change_rebuilds_transitive_consumers(self):
        state = fixture()
        built(state, 'x', 'new-x')
        prior = copy.deepcopy(state['interfaces'])
        built(state, 'y', 'new-y', prior)
        self.assertEqual(set(TX.next_packages(state)), {'z'})
        built(state, 'z', 'new-z', state['interfaces'])
        self.assertEqual(TX.next_packages(state), {})

    def test_unchanged_interface_does_not_propagate_release_only_changes(self):
        state = fixture()
        built(state, 'x', 'old-x')
        self.assertEqual(TX.next_packages(state), {})
        record = {'name': 'x', 'sha512': 'one', 'interface': {'provides': ['libx.so.1()(64bit)'], 'files': [['/usr/lib64/libx.so.1', 'same']]}}
        changed = dict(record, sha512='two')
        self.assertEqual(TX.fingerprint([record]), TX.fingerprint([changed]))
        changed = dict(record, interface={'provides': ['libx.so.2()(64bit)'], 'files': []})
        self.assertNotEqual(TX.fingerprint([record]), TX.fingerprint([changed]))

    def test_generated_runtime_requirements_and_actual_lock_inputs_are_edges(self):
        state = fixture()
        built(state, 'x', 'new-x')
        state['catalog']['y']['targets']['aarch64']['requires'] = []
        state['catalog']['y']['targets']['x86_64']['requires'] = []
        state['baseline']['aarch64'] = [{'source': 'y', 'provides': ['y'], 'requires': ['libx.so.1()(64bit)']},
                                        {'source': 'x', 'provides': ['libx.so.1()(64bit)'], 'requires': []}]
        self.assertIn('y', TX.next_packages(state))
        state['baseline']['aarch64'] = []
        built(state, 'unrelated', 'old-unrelated')
        state['builds']['unrelated']['targets']['aarch64']['consumed'] = ['x']
        self.assertIn('unrelated', TX.next_packages(state))

    def test_explicit_tool_relationships_are_part_of_the_closure(self):
        state = fixture()
        state['policy'] = {'x': ['unrelated']}
        built(state, 'x', 'new-x')
        self.assertEqual(set(TX.next_packages(state)), {'y', 'unrelated'})

    def test_no_public_payload_has_a_stable_empty_interface(self):
        first = {'name': 'docs', 'interface': {'provides': [], 'files': []}}
        self.assertEqual(TX.fingerprint([first]), TX.fingerprint([]))

    def test_changed_dependencies_are_built_before_consumers_need_their_sources(self):
        state = fixture()
        state['requested'] = ['x', 'y', 'z', 'unrelated']
        self.assertEqual(TX.ready_packages(state, set(state['requested'])), ['unrelated', 'x'])
        built(state, 'x', 'old-x')
        built(state, 'unrelated', 'old-unrelated')
        self.assertEqual(TX.ready_packages(state, set(TX.next_packages(state))), ['y'])
        built(state, 'y', 'old-y')
        self.assertEqual(TX.ready_packages(state, set(TX.next_packages(state))), ['z'])

    def test_dependency_cycles_bootstrap_together_before_their_consumers(self):
        state = fixture()
        for arch in TX.ARCHES:
            state['catalog']['x']['targets'][arch]['requires'] = ['y-devel']
        self.assertEqual(TX.ready_packages(state, {'x', 'y', 'z'}), ['x', 'y'])
        for arch in TX.ARCHES:
            state['catalog']['x']['targets'][arch]['requires'].append('unrelated-devel')
        self.assertEqual(TX.ready_packages(state, {'x', 'y', 'z', 'unrelated'}), ['unrelated'])

    def test_last_wave_refuses_an_unsettled_closure_without_advancing_state(self):
        state = fixture()
        state.update(pending=['x'], wave=7)
        built(state, 'x', 'new-x')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'state.json'
            TX.write(path, state)
            original = path.read_bytes()
            args = type('Args', (), {'state': path, 'artifacts': Path(temporary), 'final': True})()
            record = {'view': state['interfaces'], 'binaries': {'x.rpm': 'checksum'}, 'consumed': []}
            rpm = {'name': 'x', 'source': 'x', 'arch': 'noarch', 'sha512': 'checksum',
                   'provides': ['x-devel'], 'requires': [],
                   'interface': {'provides': ['libx.so.2'], 'files': []}}
            with patch.object(TX, 'checked_binaries', return_value=record), patch.object(TX, 'inspect_rpm', return_value=rpm):
                with self.assertRaisesRegex(ValueError, 'did not settle'):
                    TX.advance(args)
            self.assertEqual(path.read_bytes(), original)


class RepositoryMetadata(unittest.TestCase):
    def test_published_locations_and_source_families_survive_freezing(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            (repository / 'repodata').mkdir()
            (repository / 'repodata/repomd.xml').write_text('<repomd><data type="primary"><location href="repodata/primary.xml"/></data></repomd>')
            (repository / 'repodata/primary.xml').write_text('''<metadata><package>
              <name>libx</name><checksum type="sha256">abc</checksum>
              <location xml:base="https://example.org/rolling/x86_64/" href="libx.rpm"/>
              <format><sourcerpm>x-stream-1-1.src.rpm</sourcerpm>
              <provides><entry name="libx.so.1()(64bit)"/></provides><requires/></format>
              </package></metadata>''')
            record, = TX.baseline_packages(repository)
            self.assertEqual(record['source'], 'x-stream')
            self.assertEqual(record['url'], 'https://example.org/rolling/x86_64/libx.rpm')
            self.assertEqual(record['checksum'], 'sha256:abc')


if __name__ == '__main__':
    unittest.main()
