"""Exercise rebuild closure through the same state interface used by workers."""

import argparse
import copy
import errno
import hashlib
import http.server
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
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
                                          'requires': requires, 'build_requires': requires,
                                          'candidate_repository': {'exclude': []},
                                          'outputs': [{'name': name, 'provides': [name, name + '-devel']}]}
                                    for arch in TX.ARCHES}}
    return {'catalog': catalog, 'baseline': baseline, 'builds': {}, 'interfaces': {},
            'baseline_interfaces': {}, 'policy': {}}


def built(state, name, fingerprint, view=None):
    state['baseline_interfaces'][name] = {arch: 'old-' + name for arch in TX.ARCHES}
    state['interfaces'][name] = {arch: fingerprint for arch in TX.ARCHES}
    state['builds'][name] = {'view': copy.deepcopy(view or {}), 'targets': {
        arch: {'requires': [], 'provides': [name + '-devel'], 'consumed': [], 'rpms': []} for arch in TX.ARCHES}}


class RebuildClosure(unittest.TestCase):
    def test_archive_metadata_does_not_rebuild_consumers_but_contents_and_order_do(self):
        def archive(entries, timestamp, owner):
            data = b'!<arch>\n'
            for name, content in entries:
                data += f'{name:<16}{timestamp:<12}{owner:<6}{owner:<6}{"100644":<8}{len(content):<10}`\n'.encode()
                data += content + (b'\n' if len(content) % 2 else b'')
            return io.BytesIO(data)
        entries = [('/', b'symbol index'), ('one.o/', b'object code'), ('two.o/', b'other code')]
        first = TX.archive_fingerprint(archive(entries, 100, 0))
        self.assertEqual(first, TX.archive_fingerprint(archive(entries, 200, 65534)))
        self.assertNotEqual(first, TX.archive_fingerprint(archive(entries[::-1], 100, 0)))
        self.assertNotEqual(first, TX.archive_fingerprint(archive([*entries[:2], ('two.o/', b'new code')], 100, 0)))
        with self.assertRaisesRegex(ValueError, 'truncated'):
            TX.archive_fingerprint(io.BytesIO(archive(entries, 100, 0).getvalue()[:-3]))

    def test_build_order_uses_root_filters_and_not_runtime_dependencies(self):
        state = fixture()
        for arch in TX.ARCHES:
            for package, requires in [('x', []), ('y', ['compiler']), ('z', ['compiler'])]:
                target = state['catalog'][package]['targets'][arch]
                target.update(build_requires=requires, candidate_repository={'exclude': ['x*']},
                              outputs=[{'name': package, 'provides': [package, 'compiler']}])
            # x and y advertise the same compiler, but this root excludes x.
            # y's output has a runtime edge to z; it does not build with z.
            state['catalog']['y']['targets'][arch]['build_requires'] = []
            state['catalog']['y']['targets'][arch]['requires'] = ['z-devel']
        self.assertEqual(TX.build_dependencies(state, 'z', 'x86_64'), {'y'})
        self.assertEqual(TX.ready_packages(state, {'x', 'y', 'z'}), ['x', 'y'])

    def test_seed_only_root_cannot_wait_for_candidates_it_does_not_use(self):
        state = fixture()
        for arch in TX.ARCHES:
            target = state['catalog']['x']['targets'][arch]
            target.update(build_requires=['y-devel'], candidate_repository=None,
                          outputs=[{'name': 'x', 'provides': ['x-devel']}])
        self.assertEqual(TX.build_dependencies(state, 'x', 'x86_64'), set())
        self.assertEqual(TX.ready_packages(state, {'x', 'y'}), ['x'])

    def test_excluded_alternative_provider_does_not_invalidate_consumers(self):
        state = fixture()
        for arch in TX.ARCHES:
            state['catalog']['z']['targets'][arch].update(
                requires=['libcompiler.so.1'], candidate_repository={'exclude': ['x*']})
            for provider in ['x', 'y']:
                target = state['catalog'][provider]['targets'][arch]
                target['outputs'] = [{'name': provider, 'provides': [provider]}]
                state['baseline'][arch].append({'name': provider, 'source': provider,
                                               'provides': ['libcompiler.so.1'], 'requires': []})
        built(state, 'z', 'old-z')
        built(state, 'x', 'new-x')
        self.assertNotIn('z', TX.next_packages(state))
        built(state, 'y', 'new-y')
        self.assertIn('z', TX.next_packages(state))

    def test_recorded_inputs_and_explicit_policy_still_invalidate_excluded_providers(self):
        state = fixture()
        built(state, 'x', 'new-x')
        for package in ['z', 'unrelated']:
            built(state, package, 'old-' + package)
            for arch in TX.ARCHES:
                state['catalog'][package]['targets'][arch]['candidate_repository'] = None
        state['builds']['z']['targets']['x86_64']['consumed'] = ['x']
        state['policy']['x'] = ['unrelated']
        reasons = TX.next_packages(state)
        self.assertIn('z', reasons)
        self.assertIn('unrelated', reasons)

    def test_each_wave_records_the_previous_waves_as_its_build_inputs(self):
        state = fixture()
        state.update(schema=1, requested=['x', 'y', 'z'], pending=['x'], wave=0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = argparse.Namespace(state=root / 'state.json', artifacts=root, final=False)
            TX.write(args.state, state)
            for wave, package, following in [(0, 'x', ['y']), (1, 'y', ['z']), (2, 'z', [])]:
                inputs = copy.deepcopy(state['interfaces'])
                rpms = {}
                for arch in TX.ARCHES:
                    directory = TX.binary_directory(root, package, arch, wave)
                    directory.mkdir(parents=True)
                    rpm = directory / f'{package}-1-1.{arch}.rpm'
                    rpm.write_bytes(f'{package} compiled against {inputs} on {arch}'.encode())
                    TX.write(directory / 'source-manifest.json', {
                        'package': package, 'arch': arch, 'view': inputs,
                        'binaries': {rpm.name: TX.digest(rpm)}, 'consumed': sorted(inputs),
                    })
                    rpms[rpm] = {
                        'name': package, 'source': package, 'file': rpm.name, 'arch': arch,
                        'sha256': TX.digest(rpm), 'sha512': TX.digest(rpm, 'sha512'),
                        'requires': [], 'provides': [package + '-devel'],
                        'interface': {'provides': [], 'files': [[f'/usr/include/{package}.h', 'new']]},
                    }
                with patch.object(TX, 'inspect_rpm', side_effect=rpms.__getitem__), \
                     patch.object(TX, 'baseline_interface', return_value='old'), \
                     patch.object(TX, 'select_wave', side_effect=lambda state, args, waiting: TX.ready_packages(state, waiting)):
                    TX.advance(args)
                state = json.loads(args.state.read_text())
                self.assertEqual(state['pending'], following)
                self.assertEqual(state['builds'][package]['view'], inputs)
                self.assertEqual(state['builds'][package]['wave'], wave)
                self.assertEqual(set(inputs), set(['x', 'y', 'z'][:wave]))
            self.assertEqual(state['builds']['z']['view']['x'], state['interfaces']['x'])
            self.assertEqual(state['builds']['z']['view']['y'], state['interfaces']['y'])

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
        state['baseline']['aarch64'] = [{'name': 'y', 'source': 'y', 'provides': ['y'], 'requires': ['libx.so.1()(64bit)']},
                                        {'name': 'x', 'source': 'x', 'provides': ['libx.so.1()(64bit)'], 'requires': []}]
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
            state['catalog']['x']['targets'][arch]['build_requires'] = ['y-devel']
        self.assertEqual(TX.ready_packages(state, {'x', 'y', 'z'}), ['x', 'y'])
        for arch in TX.ARCHES:
            state['catalog']['x']['targets'][arch]['requires'].append('unrelated-devel')
            state['catalog']['x']['targets'][arch]['build_requires'].append('unrelated-devel')
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
            with patch.object(TX, 'checked_binaries', return_value=record), patch.object(TX, 'inspect_rpm', return_value=rpm), \
                 patch.object(TX, 'select_wave', side_effect=lambda state, args, waiting: TX.ready_packages(state, waiting)):
                with self.assertRaisesRegex(ValueError, 'did not settle'):
                    TX.advance(args)
            self.assertEqual(path.read_bytes(), original)


class RepositoryMetadata(unittest.TestCase):
    @staticmethod
    def response(body):
        response = io.BytesIO(body)
        response.headers = {'Content-Length': str(len(body))}
        return response

    def test_baseline_connection_failures_retry_without_publishing_partial_files(self):
        body = b'verified published RPM'
        entry = {'url': 'https://example.invalid/package.rpm',
                 'checksum': 'sha256:' + hashlib.sha256(body).hexdigest()}
        reset = TX.urllib.error.URLError(ConnectionResetError('connection reset by peer'))
        unavailable = TX.urllib.error.HTTPError(entry['url'], 503, 'unavailable', {}, None)
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(TX, 'open_url', side_effect=[reset, unavailable, self.response(body)]) as request, \
                patch.object(TX.time, 'sleep') as sleep:
            directory = Path(temporary)
            result = TX.baseline_rpm(entry, directory)
            self.assertEqual(result.read_bytes(), body)
            self.assertEqual(TX.baseline_rpm(entry, directory), result)
            self.assertEqual(list(directory.iterdir()), [result])
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [15, 45])

    def test_short_http_response_is_retried_and_only_verified_bytes_are_published(self):
        body = b'verified published RPM'
        attempts = []
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            destination = directory / (hashlib.sha256(body).hexdigest() + '.rpm')
            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    attempts.append(destination.exists())
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body[:4] if len(attempts) == 1 else body)
                    self.close_connection = True

                def log_message(self, *args):
                    pass

            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                entry = {'url': f'http://127.0.0.1:{server.server_port}/package.rpm',
                         'checksum': 'sha256:' + hashlib.sha256(body).hexdigest()}
                with patch.object(TX.time, 'sleep') as sleep:
                    self.assertEqual(TX.baseline_rpm(entry, directory), destination)
                self.assertEqual(attempts, [False, False])
                self.assertEqual(destination.read_bytes(), body)
                self.assertEqual(list(directory.iterdir()), [destination])
                sleep.assert_called_once_with(15)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_repository_retry_limit_and_permanent_http_failures(self):
        url = 'https://example.invalid/state.json'
        reset = TX.urllib.error.URLError(ConnectionResetError('connection reset by peer'))
        for error, attempts in [(reset, 3),
                                (TX.urllib.error.HTTPError(url, 404, 'not found', {}, None), 1),
                                (TX.urllib.error.HTTPError(url, 403, 'forbidden', {}, None), 1),
                                (TX.urllib.error.URLError('unknown failure'), 1)]:
            with self.subTest(error=error), patch.object(TX, 'open_url', side_effect=error) as request, \
                    patch.object(TX.time, 'sleep') as sleep:
                with self.assertRaises(type(error)):
                    TX.read_remote(url, json.load)
                self.assertEqual(request.call_count, attempts)
                self.assertEqual(sleep.call_count, attempts - 1)

    def test_baseline_integrity_and_storage_failures_do_not_retry(self):
        entry = {'url': 'https://example.invalid/package.rpm',
                 'checksum': 'sha256:' + hashlib.sha256(b'expected bytes').hexdigest()}
        for disk_error in [False, True]:
            with self.subTest(disk_error=disk_error), tempfile.TemporaryDirectory() as temporary, \
                    patch.object(TX, 'open_url', return_value=self.response(b'other bytes')) as request, \
                    patch.object(TX.time, 'sleep') as sleep:
                directory = Path(temporary)
                if disk_error:
                    with patch.object(TX.shutil, 'copyfileobj', side_effect=OSError(errno.ENOSPC, 'disk full')):
                        with self.assertRaises(OSError):
                            TX.baseline_rpm(entry, directory)
                else:
                    with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                        TX.baseline_rpm(entry, directory)
                self.assertEqual(list(directory.iterdir()), [])
                request.assert_called_once()
                sleep.assert_not_called()

    def test_published_json_read_recovers_after_a_connection_reset(self):
        reset = TX.urllib.error.URLError(ConnectionResetError('connection reset by peer'))
        with patch.object(TX, 'open_url', side_effect=[reset, self.response(b'{"hashes": {}}')]), \
                patch.object(TX.time, 'sleep') as sleep:
            self.assertEqual(TX.read_remote('https://example.invalid/state.json', json.load), {'hashes': {}})
        sleep.assert_called_once_with(15)

    def test_file_baseline_with_a_plus_in_its_release_is_copied_into_the_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'published/x-1-1+build1.rpm'
            source.parent.mkdir()
            source.write_bytes(b'baseline RPM bytes')
            checksum = TX.digest(source)
            repository = root / 'snapshot'
            (repository / 'repodata').mkdir(parents=True)
            (repository / 'repodata/repomd.xml').write_text('<repomd><data type="primary"><location href="repodata/primary.xml"/></data></repomd>')
            (repository / 'repodata/primary.xml').write_text(f'''<metadata xmlns="http://linux.duke.edu/metadata/common"><package>
              <checksum type="sha256">{checksum}</checksum>
              <location xml:base="{source.parent.as_uri()}" href="{source.name}"/>
              </package></metadata>''')
            rewritten = []
            def modify(*arguments):
                self.assertIn('xmlns="http://linux.duke.edu/metadata/common"', Path(arguments[-2]).read_text())
                self.assertNotIn('ns0:', Path(arguments[-2]).read_text())
                rewritten.append(TX.ET.parse(arguments[-2]).find('{*}package/{*}location').attrib)
            with patch.object(TX, 'run', side_effect=modify):
                TX.localise_repository(repository)
            self.assertEqual(rewritten, [{'href': checksum + '.rpm'}])
            self.assertEqual((repository / (checksum + '.rpm')).read_bytes(), source.read_bytes())

    def test_repository_downloads_identify_the_builder_instead_of_the_blocked_python_agent(self):
        with patch.object(TX.urllib.request, 'urlopen') as open_url:
            TX.open_url('https://example.invalid/package.rpm')
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header('User-agent'), 'eternal-package-builder/1')
        self.assertEqual(open_url.call_args.kwargs['timeout'], 120)

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




class TransactionReuse(unittest.TestCase):
    def snapshot(self, root):
        state = fixture()
        for name in state['catalog']:
            built(state, name, 'current-' + name)
        for name, build in state['builds'].items():
            build.update(wave=3, view=copy.deepcopy(state['interfaces']))
            for arch in TX.ARCHES:
                directory = TX.binary_directory(root / 'artifacts', name, arch, 3)
                directory.mkdir(parents=True)
                path = directory / (name + '.rpm')
                path.write_bytes((name + arch).encode())
                TX.write(directory / 'source-manifest.json', {
                    'package': name, 'arch': arch, 'binaries': {path.name: TX.digest(path)}})
                build['targets'][arch]['rpms'] = [{'file': path.name, 'sha256': TX.digest(path),
                                                     'name': name, 'source': name, 'provides': [name + '-devel']}]
        state.update(schema=1, commit='old', tree='old-tree', wave=4, build_release=100,
                     pending=[], requested=list(state['catalog']), repositories={'x86_64': 'old'})
        previous = root / 'previous/state.json'
        for arch in TX.ARCHES:
            (previous.parent / 'baseline' / arch).mkdir(parents=True)
        TX.write(previous, state)
        return state, argparse.Namespace(previous=previous, state=root / 'new/state.json',
                                         artifacts=root / 'artifacts', commit='new', build_release=200)

    def capture(self, *args):
        if 'status' in args:
            return ''
        return {'HEAD': 'new', 'old^{tree}': 'old-tree', 'new^{tree}': 'new-tree'}.get(args[-1], 'policy-blob')

    def test_changed_context_rebuilds_only_its_owner_and_preserves_input_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            before, args = self.snapshot(Path(temporary))
            def inputs(tree, package):
                return 'new' if tree == 'new-tree' and package == 'z' else 'same'
            with patch.object(TX, 'capture', side_effect=self.capture), \
                 patch.object(TX, 'catalog', return_value=before['catalog']), \
                 patch.object(TX, 'build_inputs', side_effect=inputs), \
                 patch.object(TX, 'baseline_packages', return_value=[]), patch.object(TX, 'emit'), \
                 patch.object(TX, 'select_wave', side_effect=lambda state, args, waiting: TX.ready_packages(state, waiting)):
                TX.reuse(args)
            state = json.loads(args.state.read_text())
            self.assertEqual(state['pending'], ['z'])
            self.assertEqual(state['invalidated'], ['z'])
            self.assertEqual(state['builds'], before['builds'])
            self.assertEqual(state['interfaces'], before['interfaces'])
            self.assertEqual(state['reused_from']['packages'], ['unrelated', 'x', 'y'])
            self.assertEqual(state['wave_start'], 4)
            self.assertNotIn('repositories', state)

    def test_tampered_candidate_is_rejected_before_new_state_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            before, args = self.snapshot(Path(temporary))
            next(args.artifacts.rglob('*.rpm')).write_bytes(b'tampered')
            with patch.object(TX, 'capture', side_effect=self.capture), \
                 patch.object(TX, 'catalog', return_value=before['catalog']), \
                 patch.object(TX, 'build_inputs', return_value='same'), \
                 patch.object(TX, 'baseline_packages', return_value=[]):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    TX.reuse(args)
            self.assertFalse(args.state.exists())

    def test_rebased_tree_and_transport_changes_do_not_change_build_inputs(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
            git('init', '--quiet')
            for name in ['packages/x/package.yaml', 'packages/x/files/context', 'profiles/root.yaml',
                         'scripts/package-artifacts.py', 'scripts/actions-build.py', '.rpmx-revision']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            def commit():
                git('add', '.')
                git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '--quiet', '--allow-empty', '-m', 'test')
                return git('rev-parse', 'HEAD^{tree}')
            old = commit()
            (root / 'scripts/actions-build.py').write_text('new transport')
            transport = commit()
            with patch.object(TX, 'ROOT', root):
                original = TX.build_inputs(old, 'x')
                self.assertEqual(original, TX.build_inputs(transport, 'x'))
                for filename in ['packages/x/files/context', 'profiles/root.yaml',
                                 'scripts/package-artifacts.py', '.rpmx-revision']:
                    path = root / filename
                    path.write_text('changed')
                    changed = commit()
                    self.assertNotEqual(original, TX.build_inputs(changed, 'x'), filename)
                    path.write_text('original')
                    commit()

    def test_unsettled_or_misbound_snapshots_cannot_be_reused(self):
        for field, value, message in [('pending', ['x'], 'settled'),
                                      ('tree', 'wrong-tree', 'source tree'),
                                      ('baseline', {'x86_64': ['wrong'], 'aarch64': []}, 'baseline metadata')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                before, args = self.snapshot(Path(temporary))
                before[field] = value
                TX.write(args.previous, before)
                with patch.object(TX, 'capture', side_effect=self.capture), \
                     patch.object(TX, 'catalog', return_value=before['catalog']), \
                     patch.object(TX, 'build_inputs', return_value='same'), \
                     patch.object(TX, 'baseline_packages', return_value=[]):
                    with self.assertRaisesRegex(ValueError, message):
                        TX.reuse(args)
                self.assertFalse(args.state.exists())



class WaveReadiness(unittest.TestCase):
    def test_cycle_releases_only_resolvable_members_on_every_architecture(self):
        state = fixture()
        state.update(wave=0, build_release=100)
        for arch in TX.ARCHES:
            state['catalog']['x']['targets'][arch]['build_requires'] = ['y-devel']
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(state=Path(temporary) / 'state.json')
            def resolve(rpmx, recipe, arch, repository, cache, output, release):
                self.assertTrue(repository.startswith('file://'))
                if recipe.parent.name == 'x' and arch == 'aarch64':
                    return {'code': 'RPMX-ROOT-007', 'message': 'missing y-devel'}
                return None
            with patch.object(TX, 'view') as view, patch.object(TX.recipe_inputs, 'resolve', side_effect=resolve):
                self.assertEqual(TX.select_wave(state, args, {'x', 'y', 'z'}), ['y'])
                view.assert_called_once()
            self.assertEqual(state['blocked']['x']['providers'], ['y'])
            self.assertEqual(set(state['blocked']['x']['targets']), {'aarch64'})
            with patch.object(TX, 'view'), patch.object(TX.recipe_inputs, 'resolve', return_value=None):
                self.assertEqual(TX.select_wave(state, args, {'x', 'y', 'z'}), ['x', 'y'])
                self.assertEqual(state['blocked'], {})

    def test_missing_seed_fails_instead_of_finishing_an_empty_wave(self):
        state = fixture()
        state.update(wave=0, build_release=100)
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(state=Path(temporary) / 'state.json')
            with patch.object(TX, 'view'), patch.object(TX.recipe_inputs, 'resolve', return_value={
                    'code': 'RPMX-ROOT-007', 'message': 'missing seed-devel'}):
                with self.assertRaisesRegex(ValueError, 'compatible seed') as failure:
                    TX.select_wave(state, args, {'x'})
                self.assertIn('seed-devel', str(failure.exception))

    def test_resolution_infrastructure_failures_are_not_deferred(self):
        state = fixture()
        state.update(wave=0, build_release=100)
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(state=Path(temporary) / 'state.json')
            with patch.object(TX, 'view'), patch.object(TX.recipe_inputs, 'resolve', side_effect=RuntimeError('metadata unavailable')):
                with self.assertRaisesRegex(RuntimeError, 'metadata unavailable'):
                    TX.select_wave(state, args, {'x'})


if __name__ == '__main__':
    unittest.main()
