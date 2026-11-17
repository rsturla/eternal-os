"""Candidate transport excludes source/evidence RPMs and never overwrites peers."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml

SPEC = importlib.util.spec_from_file_location('candidate_pool', Path(__file__).resolve().parents[1] / 'scripts/candidate-pool.py')
POOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POOL)


class CandidatePool(unittest.TestCase):
    def test_fixed_candidate_and_evidence_artifacts_can_be_replaced_on_job_retry(self):
        workflow = yaml.safe_load((Path(__file__).resolve().parents[1] /
                                  '.github/workflows/_build-packages.yml').read_text())
        expected = {'candidate', 'build', 'rpm', 'acceptance'}
        found = set()
        for job in ('build', 'accept'):
            for step in workflow['jobs'][job]['steps']:
                if not step.get('uses', '').startswith('actions/upload-artifact@'):
                    continue
                options = step['with']
                name = options['name']
                prefix = name.split('-')[0]
                if prefix in expected:
                    self.assertEqual(name, prefix + '-${{ matrix.package }}-${{ matrix.arch }}')
                    self.assertIs(options.get('overwrite'), True,
                                  f'{name} must replace its prior attempt rather than fail with a name conflict')
                    found.add(prefix)
        self.assertEqual(found, expected)

    def test_only_direct_canonical_binary_outputs_travel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            for name in ('gcc-1-1.x86_64.rpm', 'data-1-1.noarch.rpm', 'gcc-1-1.aarch64.rpm', 'gcc-1-1.src.rpm'):
                (source / name).write_text(name)
            (source / 'evidence').mkdir()
            (source / 'evidence/probe-1-1.x86_64.rpm').write_text('unrelated')
            (source / 'link-1-1.x86_64.rpm').symlink_to(source / 'gcc-1-1.x86_64.rpm')
            (source / 'build-policy.json').write_text(json.dumps({'build_release': '123'}))
            members = root / 'members'
            POOL.export(source, members / 'candidate-gcc-x86_64', 'x86_64')
            POOL.assemble(members, root / 'pool', 'x86_64')
            self.assertEqual({p.name for p in (root / 'pool').iterdir()}, {'gcc-1-1.x86_64.rpm', 'data-1-1.noarch.rpm'})
            self.assertEqual(json.loads((members / 'candidate-gcc-x86_64/build-policy.json').read_text())['build_release'], '123')

    def test_duplicate_or_foreign_candidates_fail_before_pool_creation(self):
        for bad in ('duplicate', 'foreign', 'nested', 'symlink'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                members = root / 'members'
                for name in ('one', 'two'):
                    member = members / name
                    member.mkdir(parents=True)
                    (member / 'build-policy.json').write_text('{"build_release":null}')
                    (member / f'{name}-1-1.x86_64.rpm').write_text(name)
                second = members / 'two'
                if bad == 'duplicate':
                    (second / 'one-1-1.x86_64.rpm').write_text('conflicting')
                elif bad == 'foreign':
                    (second / 'two-1-1.aarch64.rpm').write_text('foreign')
                elif bad == 'nested':
                    (second / 'evidence').mkdir()
                else:
                    (second / 'link-1-1.x86_64.rpm').symlink_to(second / 'two-1-1.x86_64.rpm')
                with self.assertRaises(ValueError):
                    POOL.assemble(members, root / 'pool', 'x86_64')
                self.assertFalse((root / 'pool').exists())
