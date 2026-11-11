"""Exercise package selection and cache keys against a small git checkout."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BuildSelectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'scripts').mkdir()
        for name in ('affected.sh', 'package-hash.sh', 'list-packages.sh'):
            shutil.copy2(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        for name in ('glibc-2.44', 'consumer', 'eternal-release'):
            path = self.root / 'packages' / name / 'package.yaml'
            path.parent.mkdir(parents=True)
            path.write_text(f'name: {name}\n')
        (self.root / 'packages/consumer/package.yaml').write_text(
            'name: consumer\nbuild:\n  sysroot: [glibc-devel]\n'
        )
        (self.root / 'profiles').mkdir()
        (self.root / 'profiles' / 'bootstrap.yaml').write_text('seed: fedora\n')
        (self.root / '.rpmx-revision').write_text('first\n')
        (self.root / 'rpmx-defaults.yaml').write_text('schema: 1\n')
        self.run_git('init', '-q')
        self.run_git('config', 'user.email', 'test@example.test')
        self.run_git('config', 'user.name', 'Test')
        self.run_git('add', '.')
        self.run_git('commit', '-qm', 'initial')

    def run_git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True, text=True)

    def selected(self):
        output = subprocess.check_output([self.root / 'scripts/affected.sh', '--base', 'HEAD', '--json'], cwd=self.root, text=True)
        return json.loads(output)

    def hashes(self):
        output = subprocess.check_output([self.root / 'scripts/package-hash.sh', 'glibc-2.44', 'consumer'], cwd=self.root, text=True)
        return dict(line.split() for line in output.splitlines())

    def test_recipe_change_selects_only_its_source(self):
        (self.root / 'packages/glibc-2.44/package.yaml').write_text('changed\n')
        self.assertEqual(self.selected(), ['glibc-2.44'])

    def test_profile_change_selects_all_packages(self):
        (self.root / 'profiles/bootstrap.yaml').write_text('changed\n')
        self.assertEqual(self.selected(), ['consumer', 'eternal-release', 'glibc-2.44'])

    def test_builder_change_selects_canary(self):
        (self.root / '.rpmx-revision').write_text('second\n')
        self.assertEqual(self.selected(), ['eternal-release'])

    def test_hash_tracks_direct_recipe_and_shared_inputs(self):
        before = self.hashes()
        (self.root / 'packages/glibc-2.44/package.yaml').write_text('changed\n')
        after_recipe = self.hashes()
        self.assertNotEqual(before['glibc-2.44'], after_recipe['glibc-2.44'])
        self.assertEqual(before['consumer'], after_recipe['consumer'])
        (self.root / 'profiles/bootstrap.yaml').write_text('changed\n')
        after_profile = self.hashes()
        self.assertNotEqual(after_recipe['consumer'], after_profile['consumer'])
        self.assertNotEqual(after_recipe['glibc-2.44'], after_profile['glibc-2.44'])


if __name__ == '__main__':
    unittest.main()
