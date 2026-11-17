"""Test the shell publisher with real RPM tools and a local S3 CLI substitute.

Requires rpmx, createrepo_c, mergerepo_c, modifyrepo_c, gpg and jq.
If dnf5 is available and the test runs as root, also test client transactions.
"""

import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ('rpmx', 'createrepo_c', 'mergerepo_c', 'modifyrepo_c', 'gpg', 'jq')
FAKE_AWS = '''#!/usr/bin/env python3
import fnmatch, json, os, pathlib, shutil, sys
args = sys.argv[1:]
if args[:1] == ['--endpoint-url']:
    args = args[2:]
with open(os.environ['AWS_TEST_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if os.environ.get('AWS_TEST_FAIL'):
    sys.exit('AccessDenied')
root = pathlib.Path(os.environ['AWS_TEST_ROOT'])
def option(name):
    return args[args.index(name) + 1]
def local(uri):
    return root / uri.removeprefix('s3://')
if args[:2] == ['s3api', 'list-objects-v2']:
    bucket = root / option('--bucket')
    keys = sorted(f.relative_to(bucket).as_posix() for f in bucket.rglob('*')
                  if f.is_file() and f.relative_to(bucket).as_posix().startswith(option('--prefix')))
    print(json.dumps({'Contents': [{'Key': k} for k in keys[:int(option('--max-keys'))]]}))
elif args[:2] == ['s3', 'cp']:
    source, dest = args[2:4]
    if source.startswith('s3://') and source.endswith('.rpm'):
        sys.exit('Historical RPM download forbidden')
    source = local(source) if source.startswith('s3://') else pathlib.Path(source)
    dest = local(dest) if dest.startswith('s3://') else pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
elif args[:2] == ['s3', 'sync']:
    source, dest = args[2:4]
    if source.startswith('s3://'):
        sys.exit('Historical repository sync forbidden')
    source, dest = pathlib.Path(source), local(dest)
    excludes = [args[i + 1] for i, arg in enumerate(args) if arg == '--exclude']
    for f in source.rglob('*'):
        rel = f.relative_to(source).as_posix()
        if f.is_file() and not any(fnmatch.fnmatchcase(rel, pattern) for pattern in excludes):
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, target)
else:
    sys.exit('Unexpected AWS command: ' + repr(args))
'''


def command(*args, **kwargs):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise AssertionError(f'{args}\n{result.stdout}\n{result.stderr}')
    return result.stdout


@unittest.skipUnless(all(shutil.which(tool) for tool in TOOLS), 'RPM publishing tools required')
class PublishTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixtures.cleanup)
        cls.fixture_root = Path(cls.fixtures.name)
        for name, version, payload, requirement in (
            ('publish-fixture', '1', 'fixture', ''),
            ('publish-fixture', '2', 'fixture', 'Requires: /opt/publish-test/kept'),
            ('publish-kept', '1', 'kept', ''),
        ):
            stage = cls.fixture_root / f'stage-{name}-{version}'
            target = stage / 'opt/publish-test' / payload
            target.parent.mkdir(parents=True)
            target.write_text(version + '\n')
            recipe = cls.fixture_root / f'{name}-{version}.yaml'
            dependency = "[\"/opt/publish-test/kept\"]" if requirement else '[]'
            recipe.write_text(f"""schema: 2
package:
  name: {name}
  version: '{version}'
  release: 1
  summary: Repository publication fixture
  license: MIT
  source-date-epoch: 1704067200
outputs:
  - name: {name}
    arch: noarch
    dependencies:
      run: {dependency}
""")
            if name == 'publish-fixture' and version == '1':
                with recipe.open('a') as stream:
                    stream.write('  - name: publish-fixture-legacy\n    arch: noarch\n    metapackage: true\n')
            binaries = cls.fixture_root / f'binary-{name}-{version}'
            command('rpmx', 'build', recipe, '--stage', stage, '--arch', 'x86_64',
                    '--output', binaries, '--no-tests', '--no-lint', '--no-index')
            (cls.fixture_root / 'RPMS/noarch').mkdir(parents=True, exist_ok=True)
            for rpm in binaries.rglob('*.rpm'):
                shutil.copy(rpm, cls.fixture_root / 'RPMS/noarch')
            sources = cls.fixture_root / 'sources'
            sources.mkdir(exist_ok=True)
            command('rpmx', 'srpm', recipe, '--sources', sources,
                    '--output', cls.fixture_root / 'SRPMS')
        cls.key = cls.fixture_root / 'signing.asc'
        command('rpmx', 'keygen', '--bits', '2048', '--output', cls.key)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.packages = self.work / 'out'
        self.site = self.work / 'site'
        self.bucket = self.work / 'storage/packages'
        self.bucket.mkdir(parents=True)
        self.log = self.work / 'aws.log'
        self.bin = self.work / 'bin'
        self.bin.mkdir()
        aws = self.bin / 'aws'
        aws.write_text(FAKE_AWS)
        aws.chmod(0o755)
        self.env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}',
                        AWS_TEST_ROOT=str(self.bucket.parent), AWS_TEST_LOG=str(self.log))

    def inputs(self, version, kept=False):
        shutil.rmtree(self.packages, ignore_errors=True)
        binary = self.packages / 'x86_64'
        source = binary / 'src'
        source.mkdir(parents=True)
        names = [f'publish-fixture-{version}-1']
        if kept:
            names.append('publish-kept-1-1')
        for name in names:
            shutil.copy(self.fixture_root / f'RPMS/noarch/{name}.noarch.rpm', binary)
            shutil.copy(self.fixture_root / f'SRPMS/{name}.src.rpm', source)

    def publish(self, signed=False, success=True, incremental=False):
        args = [ROOT / 'scripts/publish-bucket.sh', '--packages', self.packages,
                '--output', self.site, '--bucket', 'packages', '--base-url', 'https://example.invalid']
        if incremental:
            args += ['--incremental']
        if signed:
            args += ['--signing-key', self.key, '--public-key', str(self.key) + '.pub']
        result = subprocess.run([str(arg) for arg in args], env=self.env, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def records(self, channel, arch='x86_64'):
        repo = self.bucket / channel / arch
        idx = ET.parse(repo / 'repodata/repomd.xml')
        href = idx.find("{*}data[@type='primary']/{*}location").get('href')
        data = ET.fromstring(gzip.decompress((repo / href).read_bytes()))
        records = {(p.findtext('{*}name'), p.find('{*}version').get('ver')) for p in data}
        self.assertEqual(len(data), len(records), 'duplicate package records')
        return records

    def operations(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_incremental_archive_and_rolling_selection(self):
        self.inputs('1', kept=True)
        self.publish()
        old_metadata = {p: p.read_bytes() for p in (self.bucket / 'archive').rglob('repodata/*') if p.is_file() and p.name not in {'repomd.xml', 'repomd.xml.asc'}}
        self.inputs('2')
        self.log.write_text('')
        self.publish()
        self.publish()
        expected = {('publish-fixture', '1'), ('publish-fixture', '2'), ('publish-kept', '1')}
        self.assertEqual(self.records('archive'), expected)
        self.assertEqual(self.records('archive', 'SRPMS'), expected)
        self.assertEqual(self.records('rolling'), {('publish-fixture', '2')})
        self.assertFalse(list((self.site / 'archive').rglob('*.rpm')))
        for path, content in old_metadata.items():
            self.assertEqual(path.read_bytes(), content)
        for operation in self.operations():
            if operation[:2] == ['s3', 'cp'] and operation[2].startswith('s3://'):
                self.assertIn('/repodata/', operation[2])
            if operation[:2] == ['s3', 'cp'] and operation[3].startswith('s3://') and operation[3].endswith('/repomd.xml'):
                dest = operation[3]
                before = self.operations()[:self.operations().index(operation)]
                self.assertTrue(any(op[:2] == ['s3', 'sync'] and op[3] == dest.removesuffix('/repomd.xml') for op in before))
        if shutil.which('dnf5') and os.geteuid() == 0:
            self.dnf('install', 'publish-fixture-1-1')
            self.dnf('upgrade', 'publish-fixture')
            self.assertEqual((self.work / 'root/opt/publish-test/fixture').read_text().strip(), '2')
            self.assertTrue((self.work / 'root/opt/publish-test/kept').exists())

    def dnf(self, *args, signed=False):
        options = ['--setopt=probe.repo_gpgcheck=1', f'--setopt=probe.gpgkey=file://{self.key}.pub'] if signed else []
        return command('dnf5', '-y', f'--installroot={self.work}/root', '--releasever=44',
                       '--disable-repo=*', f'--repofrompath=probe,file://{self.bucket}/archive/x86_64',
                       '--setopt=probe.gpgcheck=0', '--setopt=probe.metadata_expire=0',
                       '--setopt=optional_metadata_types=filelists', *options, *args)

    def test_signed_archive_is_verified_and_resigned(self):
        self.inputs('1')
        self.publish(signed=True)
        old = (self.bucket / 'archive/x86_64/repodata/repomd.xml').read_bytes()
        self.inputs('2')
        self.publish(signed=True)
        index = self.bucket / 'archive/x86_64/repodata/repomd.xml'
        self.assertNotEqual(index.read_bytes(), old)
        home = self.work / 'verify'
        home.mkdir(mode=0o700)
        command('gpg', '--homedir', home, '--batch', '--import', str(self.key) + '.pub')
        command('gpg', '--homedir', home, '--batch', '--verify', str(index) + '.asc', index)
        if shutil.which('dnf5') and os.geteuid() == 0:
            self.dnf('makecache', signed=True)
        self.log.write_text('')
        self.assertIn('without --signing-key', self.publish(success=False).stderr)
        self.assertFalse(any(op[:2] == ['s3', 'sync'] for op in self.operations()))

        index.write_bytes(index.read_bytes() + b'\n')
        self.log.write_text('')
        self.publish(signed=True, success=False)
        self.assertFalse(any(op[:2] == ['s3', 'sync'] for op in self.operations()))

    def test_incremental_rolling_retains_other_sources_and_removes_old_outputs(self):
        self.inputs('1', kept=True)
        shutil.copy(self.fixture_root / 'RPMS/noarch/publish-fixture-legacy-1-1.noarch.rpm',
                    self.packages / 'x86_64')
        self.publish(signed=True, incremental=True)
        self.inputs('2')
        self.publish(signed=True, incremental=True)
        self.publish(signed=True, incremental=True)
        self.assertEqual(self.records('rolling'), {('publish-fixture', '2'), ('publish-kept', '1')})
        self.assertEqual(self.records('rolling', 'SRPMS'), {('publish-fixture', '2'), ('publish-kept', '1')})
        self.assertIn(('publish-fixture-legacy', '1'), self.records('archive'))
        self.assertIn(('publish-fixture', '1'), self.records('archive', 'SRPMS'))
        self.assertTrue((self.bucket / 'rolling/x86_64/publish-fixture-1-1.noarch.rpm').exists())

    def test_incremental_rolling_verifies_previous_signature(self):
        self.inputs('1', kept=True)
        self.publish(signed=True, incremental=True)
        index = self.bucket / 'rolling/x86_64/repodata/repomd.xml'
        index.write_bytes(index.read_bytes() + b'\n')
        self.inputs('2')
        self.log.write_text('')
        self.publish(signed=True, incremental=True, success=False)
        self.assertFalse(any(op[:2] == ['s3', 'sync'] for op in self.operations()))

    def test_source_rpm_collision_aborts_before_upload(self):
        self.inputs('1')
        duplicate = self.packages / 'another/aarch64/src/publish-fixture-1-1.src.rpm'
        duplicate.parent.mkdir(parents=True)
        duplicate.write_bytes(b'different SRPM with the same filename')
        result = self.publish(success=False)
        self.assertIn('conflicting source RPM', result.stderr)
        self.assertFalse(any(op[:2] == ['s3', 'sync'] for op in self.operations()))

    def test_policy_metadata_and_source_only_history_survive(self):
        self.inputs('1', kept=True)
        self.publish()
        repodata = self.bucket / 'archive/x86_64/repodata'
        group = self.work / 'comps.xml'
        group.write_text('''<comps><group><id>publish-test</id><name>Publication test</name>
<description>Fixture group</description><default>false</default><uservisible>true</uservisible>
<packagelist><packagereq type="mandatory">publish-kept</packagereq></packagelist></group></comps>''')
        advisory = self.work / 'updateinfo.xml'
        advisory.write_text('''<updates><update from="test" status="stable" type="bugfix" version="1">
<id>PUBLISH-TEST-1</id><title>Fixture advisory</title><issued date="2026-11-11 00:00:00"/>
<updated date="2026-11-11 00:00:00"/><description>Fixture advisory</description>
<references/><pkglist><collection short="archive"><name>Archive</name>
<package name="publish-fixture" epoch="0" version="1" release="1" arch="noarch" src="publish-fixture-1-1.src.rpm">
<filename>publish-fixture-1-1.noarch.rpm</filename></package></collection></pkglist></update></updates>''')
        for kind, file in [('group', group), ('updateinfo', advisory)]:
            command('modifyrepo_c', '--mdtype', kind, '--compress-type=gz', file, repodata)
        cache = repodata / 'unused-primary.sqlite'
        cache.write_bytes(b'An unused derived cache')
        cache_record = f'<data type="primary_db"><location href="repodata/{cache.name}"/><checksum type="sha256">{hashlib.sha256(cache.read_bytes()).hexdigest()}</checksum></data>'
        path = repodata / 'repomd.xml'
        path.write_text(path.read_text().replace('</repomd>', cache_record + '</repomd>'))
        self.inputs('2')
        shutil.rmtree(self.packages / 'x86_64/src')
        self.publish()
        self.assertFalse(any('unused-primary.sqlite' in op for command in self.operations() for op in command))
        self.assertFalse((self.site / 'rolling/SRPMS').exists())
        self.assertEqual(self.records('archive', 'SRPMS'), {('publish-fixture', '1'), ('publish-kept', '1')})
        index = ET.parse(repodata / 'repomd.xml')
        for kind, expected in [('group', b'publish-test'), ('updateinfo', b'PUBLISH-TEST-1')]:
            href = index.find(f"{{*}}data[@type='{kind}']/{{*}}location").get('href')
            self.assertIn(expected, gzip.decompress((repodata.parent / href).read_bytes()))

    def test_remote_errors_and_corrupt_metadata_abort_before_upload(self):
        self.inputs('1')
        self.env['AWS_TEST_FAIL'] = '1'
        self.assertIn('AccessDenied', self.publish(success=False).stderr)
        del self.env['AWS_TEST_FAIL']
        orphan = self.bucket / 'archive/x86_64/orphan.rpm'
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b'orphan')
        self.publish(success=False)
        orphan.unlink()
        self.publish()
        index = self.bucket / 'archive/x86_64/repodata/repomd.xml'
        original = index.read_bytes()
        index.write_bytes(original.replace(b'<checksum type="sha256">', b'<checksum type="sha256">0', 1))
        self.log.write_text('')
        self.assertIn('incorrect metadata checksum', self.publish(success=False).stderr)
        self.assertFalse(any(op[:2] == ['s3', 'sync'] for op in self.operations()))
        index.write_bytes(original.replace(b'</repomd>', b'<data type="modules"/></repomd>'))
        self.assertIn('unsupported metadata', self.publish(success=False).stderr)
        index.write_bytes(original.replace(b'repodata/', b'repodata/../', 1))
        self.assertIn('unsupported metadata location', self.publish(success=False).stderr)

    def test_publication_signs_tested_content_and_writes_success_marker_last(self):
        self.inputs('1', kept=True)
        spec = importlib.util.spec_from_file_location('sign_packages', ROOT / 'scripts/sign-packages.py')
        signing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(signing)
        before = {path.name: signing.content_digest(path) for path in self.packages.rglob('*.rpm')}
        (self.packages / 'build-state.json').write_text('{"schema":1,"commit":"merged"}\n')
        env = dict(self.env, PACKAGES_S3_BUCKET='packages', PACKAGES_BASE_URL='https://example.invalid',
                   RPMX_SIGNING_KEY=self.key.read_text(), RPMX_PUBLIC_KEY=Path(str(self.key) + '.pub').read_text())
        command(ROOT / 'scripts/publish-packages.sh', self.packages, env=env)
        receipt = json.loads((self.packages / 'signing.json').read_text())
        self.assertTrue(receipt['rpms'])
        for path in self.packages.rglob('*.rpm'):
            self.assertEqual(signing.content_digest(path), before[path.name])
        self.assertEqual(json.loads((self.bucket / 'build-state.json').read_text())['commit'], 'merged')
        last = self.operations()[-1]
        self.assertEqual(last[:2], ['s3', 'cp'])
        self.assertTrue(last[3].endswith('/build-state.json'))

    def test_candidate_view_replaces_source_family_and_preserves_published_locations(self):
        self.inputs('1', kept=True)
        shutil.copy(self.fixture_root / 'RPMS/noarch/publish-fixture-legacy-1-1.noarch.rpm',
                    self.packages / 'x86_64')
        self.publish()
        spec = importlib.util.spec_from_file_location('transaction', ROOT / 'scripts/build-transaction.py')
        transaction = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transaction)
        state_dir = self.work / 'transaction'
        artifacts = self.work / 'candidates'
        candidate = self.fixture_root / 'RPMS/noarch/publish-fixture-2-1.noarch.rpm'
        rpm = transaction.inspect_rpm(candidate)
        state = {'builds': {'publish-fixture': {'wave': 0, 'targets': {}}}}
        for arch in transaction.ARCHES:
            baseline = state_dir / 'baseline' / arch
            command('mergerepo_c', '--repo', self.bucket / 'rolling/x86_64',
                    '--outputdir', baseline, '--no-database', '--compress-type=gz')
            directory = transaction.binary_directory(artifacts, 'publish-fixture', arch, 0)
            directory.mkdir(parents=True)
            shutil.copy2(candidate, directory / candidate.name)
            transaction.write(directory / 'source-manifest.json', {
                'package': 'publish-fixture', 'arch': arch,
                'binaries': {candidate.name: transaction.digest(candidate)}})
            state['builds']['publish-fixture']['targets'][arch] = {'rpms': [rpm]}
        transaction.write(state_dir / 'state.json', state)
        output = self.work / 'view'
        command('python3', ROOT / 'scripts/build-transaction.py', 'view', '--state', state_dir / 'state.json',
                '--artifacts', artifacts, '--output', output)
        for arch in transaction.ARCHES:
            metadata = transaction.primary(output / arch)
            self.assertEqual({entry.findtext('{*}name') for entry in metadata}, {'publish-fixture', 'publish-kept'})
            for entry in metadata:
                location = entry.find('{*}location')
                if entry.findtext('{*}name') == 'publish-fixture':
                    self.assertEqual(location.get('href'), candidate.name)
                    self.assertNotIn('{http://www.w3.org/XML/1998/namespace}base', location.attrib)
                    self.assertEqual((output / arch / candidate.name).read_bytes(), candidate.read_bytes())
                else:
                    self.assertIn('rolling/x86_64', location.get('{http://www.w3.org/XML/1998/namespace}base', '') + location.get('href'))

    def test_metadata_input_cannot_be_deleted_by_output_cleanup(self):
        self.inputs('1')
        old = self.site / 'archive/x86_64/repodata/repomd.xml'
        old.parent.mkdir(parents=True)
        old.write_text('previous snapshot')
        result = subprocess.run([
            ROOT / 'scripts/publish-repo.sh', '--packages', self.packages,
            '--output', self.site, '--archive-release', 'archive',
            '--archive-metadata', self.site / 'archive',
        ], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not overlap', result.stderr)
        self.assertEqual(old.read_text(), 'previous snapshot')


if __name__ == '__main__':
    unittest.main()
