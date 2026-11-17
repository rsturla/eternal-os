"""Check existing PR RPMs against a newer main without recompilation."""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


QUEUE = load('queue-packages')
TRANSACTION = load('build-transaction')
PROMOTE = load('promote-packages')
ARCHES = TRANSACTION.ARCHES
HEAD, BASE, TREE = (letter * 40 for letter in 'abc')


def inputs():
    catalog = {name: {'hash': name + '-hash', 'targets': {arch: {
        'sources': [name], 'provides': [name], 'requires': ['provider'] if name == 'subject' else []}
        for arch in ARCHES}} for name in ('subject', 'provider', 'unrelated')}
    baseline = {arch: [{'source': name, 'name': name, 'checksum': name + '-old',
                        'requires': [], 'provides': [name], 'evr': ['0', '1', '90']} for name in catalog] for arch in ARCHES}
    state = {'catalog': catalog, 'baseline': baseline, 'policy': {}, 'pending': [], 'requested': ['subject'],
             'build_release': 100, 'wave': 1, 'builds': {'subject': {
                 'wave': 0, 'view': {}, 'targets': {arch: {'consumed': ['provider'], 'requires': ['provider'],
                                                        'provides': ['subject'], 'rpms': [
                                                            {'name': 'subject', 'evr': ['0', '1', '100']}]} for arch in ARCHES}}},
             'interfaces': {'subject': {arch: 'subject-new-interface' for arch in ARCHES}},
             'baseline_interfaces': {'subject': {arch: 'subject-old-interface' for arch in ARCHES}},
             'published': {'hashes': {name: item['hash'] for name, item in catalog.items()}, 'build_release': 90}}
    state['published']['hashes']['subject'] = 'before-pr'
    current = copy.deepcopy(state)
    current.update(commit=HEAD, tree=TREE, builds={}, interfaces={}, baseline_interfaces={})
    return state, current


class QueueIdentity(unittest.TestCase):
    def fixtures(self):
        event = {'merge_group': {'head_ref': 'refs/heads/gh-readonly-queue/main/pr-81-' + BASE,
                                'base_ref': 'refs/heads/main', 'head_sha': HEAD, 'base_sha': BASE}}
        pr = {'number': 81, 'state': 'open', 'base': {'ref': 'main', 'repo': {'full_name': 'owner/repo'}},
              'head': {'sha': 'd' * 40}}
        promote = Mock()
        promote.api.side_effect = [{'object': {'sha': BASE}}, pr]
        promote.git.side_effect = [HEAD, '', pr['head']['sha'], TREE, TREE]
        return event, pr, promote

    def test_one_pr_plus_current_main_is_bound_to_integrated_tree(self):
        event, pr, promote = self.fixtures()
        self.assertEqual(QUEUE.queue_pr('owner/repo', event, promote), pr)
        self.assertIn(unittest.mock.call('merge-tree', '--write-tree', BASE, pr['head']['sha']), promote.git.call_args_list)

    def test_advanced_main_wrong_checkout_extra_pr_or_wrong_target_blocks_queue(self):
        for change in ('advanced', 'checkout', 'tree', 'target', 'closed', 'pr-head'):
            with self.subTest(change=change):
                event, pr, promote = self.fixtures()
                if change == 'advanced': promote.api.side_effect = [{'object': {'sha': 'new-main'}}]
                elif change == 'checkout': promote.git.side_effect = ['old-checkout']
                elif change == 'tree': promote.git.side_effect = [HEAD, '', pr['head']['sha'], 'different-group', TREE]
                elif change == 'pr-head': promote.git.side_effect = [HEAD, '', 'different-pr-head']
                elif change == 'target': pr['base']['ref'] = 'other'
                else: pr['state'] = 'closed'
                with self.assertRaises(ValueError):
                    QUEUE.queue_pr('owner/repo', event, promote)

    def test_documentation_only_pr_does_not_need_rpm_artifacts(self):
        event, pr, promote = self.fixtures()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'event.json').write_text(json.dumps(event))
            with patch.object(QUEUE, 'load', side_effect=lambda name: promote if name == 'promote-packages' else TRANSACTION), \
                    patch.object(QUEUE.subprocess, 'check_output', return_value='[]'):
                result = QUEUE.prepare(argparse.Namespace(repository='owner/repo', event=root / 'event.json',
                                                         base_url='https://example.invalid', output=root / 'queue'))
            self.assertEqual(result['matrix'], [])
            promote.find_pr_attempt.assert_not_called()


class ReuseInputs(unittest.TestCase):
    def check(self, original, current):
        with tempfile.TemporaryDirectory() as temporary:
            return QUEUE.check_reuse(original, current, TRANSACTION, Path(temporary))

    def test_unrelated_main_recipe_and_publication_changes_reuse_old_pr_build(self):
        original, current = inputs()
        current['catalog']['unrelated']['hash'] = 'new-main-inputs'
        current['published']['hashes']['unrelated'] = 'new-main-inputs'
        current['published']['build_release'] = 200
        for arch in ARCHES:
            current['baseline'][arch][-1]['checksum'] = 'new-unrelated-rpm'
        state = self.check(original, current)
        self.assertEqual(state['tree'], TREE)
        self.assertEqual(state['builds'], original['builds'])
        self.assertEqual(state['catalog']['unrelated']['hash'], 'new-main-inputs')
        self.assertEqual(state['build_release'], 100)
        state['queue'] = {'base': BASE}
        # The release watermark stays monotonic. The existing RPM counter is
        # safe because queue validation checked its source family separately.
        published = PROMOTE.check_inputs({'tree': TREE}, state, HEAD, TREE,
                                        {name: data['hash'] for name, data in state['catalog'].items()},
                                        state['baseline'], current['published'])
        self.assertEqual(published['build_release'], 200)

    def test_changed_inputs_newer_same_source_family_and_unpublished_main_block(self):
        for change, message in [('hash', 'build inputs changed'), ('source', 'source family changed'),
                                ('unpublished', 'unpublished'), ('removed', 'build inputs changed')]:
            with self.subTest(change=change):
                original, current = inputs()
                if change == 'hash': current['catalog']['subject']['hash'] = 'new-inputs'
                elif change == 'source': current['baseline']['x86_64'][0]['checksum'] = 'new-subject'
                elif change == 'removed': del current['catalog']['subject']
                else: current['published']['hashes']['unrelated'] = 'not-published'
                with self.assertRaisesRegex(ValueError, message):
                    self.check(original, current)

    def test_changed_dependency_public_inputs_require_a_new_pr_build(self):
        original, current = inputs()
        current['baseline']['x86_64'][1]['checksum'] = 'new-provider'
        with patch.object(TRANSACTION, 'baseline_interface', side_effect=['old-abi', 'new-abi']):
            with self.assertRaisesRegex(ValueError, 'provider changed public build inputs'):
                self.check(original, current)

    def test_rpm_versions_cannot_downgrade_the_published_family(self):
        for version in (['0', '1', '80'], ['0', '1', '90'], ['0', '1~rc1', '100'], ['0', '0.9', '999']):
            with self.subTest(version=version):
                original, current = inputs()
                original['builds']['subject']['targets']['x86_64']['rpms'][0]['evr'] = version
                with self.assertRaisesRegex(ValueError, 'does not upgrade'):
                    self.check(original, current)

    def test_rpm_version_comparison_handles_epoch_and_literal_input(self):
        self.assertGreater(QUEUE.compare_evr(['1', '1', '1'], ['0', '99', '99']), 0)
        self.assertLess(QUEUE.compare_evr(['0', '1~rc1', '1'], ['0', '1', '1']), 0)
        self.assertEqual(QUEUE.compare_evr(['0', '%{lua:error("unsafe")}', '1'],
                                           ['0', '%{lua:error("unsafe")}', '1']), 0)

    def test_new_dependency_package_with_same_public_inputs_is_accepted(self):
        original, current = inputs()
        current['baseline']['x86_64'][1]['checksum'] = 'new-provider'
        with patch.object(TRANSACTION, 'baseline_interface', return_value='same-abi'):
            self.check(original, current)

    def test_actual_consumed_build_root_dependencies_are_checked(self):
        original, current = inputs()
        # This dependency is absent from declarations and runtime requirements.
        for arch in ARCHES:
            original['builds']['subject']['targets'][arch]['consumed'].append('unrelated')
        current['baseline']['x86_64'][2]['checksum'] = 'new-generator'
        with patch.object(TRANSACTION, 'baseline_interface', side_effect=['old-tool', 'new-tool']):
            with self.assertRaisesRegex(ValueError, 'unrelated changed public build inputs'):
                self.check(original, current)

    def test_new_main_consumer_must_be_in_the_pr_rebuild_closure(self):
        original, current = inputs()
        for arch in ARCHES:
            current['catalog']['unrelated']['targets'][arch]['requires'] = ['subject']
        with self.assertRaisesRegex(ValueError, 'additional dependency rebuilds'):
            self.check(original, current)


if __name__ == '__main__':
    unittest.main()
