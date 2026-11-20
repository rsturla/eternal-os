"""Check shared source profiles and distinguish missing inputs from broken resolution."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('recipe_inputs', ROOT / 'scripts/recipe-inputs.py')
INPUTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INPUTS)


class RecipeInputs(unittest.TestCase):
    def test_readiness_preserves_profile_policy_and_only_defers_solver_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe = root / 'package.yaml'
            recipe.write_text('build:\n  root:\n    profile: profile.yaml\n')
            profile = {'archs': ['x86_64', 'aarch64'], 'packages': {'install': ['tool >= 2']},
                       'repositories': [{'id': 'eternal', 'baseurl': 'https://old.invalid/$basearch', 'exclude': ['old*']},
                                        {'id': 'seed', 'baseurl': 'https://seed.invalid/$basearch', 'exclude': ['openssl*']}]}
            (root / 'profile.yaml').write_text(yaml.safe_dump(profile))
            for index, (code, message, blocked) in enumerate([
                (None, None, False),
                ('RPMX-ROOT-007', 'build test upstream preparation: Failed to resolve the transaction: missing tool', True),
                ('RPMX-ROOT-007', 'repository metadata download failed', False),
                ('RPMX-ROOT-019', 'authentication failed', False),
                ('RPMX-INCLUDE-001', 'invalid recipe', False),
            ]):
                output = root / str(index)
                def execute(command, **options):
                    self.assertIn('inputs', command)
                    self.assertIn('aarch64', command)
                    selected = yaml.safe_load((output / 'profile.yaml').read_text())
                    self.assertEqual(selected['repositories'][0]['baseurl'], 'file:///snapshot/$basearch')
                    self.assertEqual(selected['repositories'][0]['exclude'], ['old*'])
                    self.assertEqual(selected['repositories'][1], profile['repositories'][1])
                    self.assertEqual(selected['packages'], profile['packages'])
                    (output / 'run-report.json').write_text(json.dumps({
                        'outcome': 'failed' if code else 'passed',
                        'primary': {'code': code, 'message': message} if code else None}))
                    return subprocess.CompletedProcess(command, 4 if code else 0, 'report', 'detail')
                with self.subTest(code=code, message=message), patch.object(INPUTS.subprocess, 'run', side_effect=execute):
                    if code and not blocked:
                        with self.assertRaises(RuntimeError):
                            INPUTS.resolve('rpmx', recipe, 'aarch64', 'file:///snapshot', root / 'cas', output, 100)
                    else:
                        result = INPUTS.resolve('rpmx', recipe, 'aarch64', 'file:///snapshot', root / 'cas', output, 100)
                        self.assertEqual(result is not None, blocked)
