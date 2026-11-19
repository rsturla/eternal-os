"""Test the GitHub boundary without replacing the RPM execution engine."""

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('actions_build', ROOT / 'scripts/actions-build.py')
ACTIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACTIONS)
SHA = 'a' * 40


class ArtifactTransport(unittest.TestCase):
    def archive(self, filename='state.json'):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(filename, '{"schema":1}')
        return stream.getvalue()

    def responses(self, archive, digest=None):
        return [{'artifacts': [{'id': 7, 'name': 'snapshot', 'expired': False,
                                'digest': digest or 'sha256:' + hashlib.sha256(archive).hexdigest()}]}, archive]

    def test_archive_corruption_is_rejected_before_extraction(self):
        archive = self.archive()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'out'
            with patch.object(ACTIONS, 'api', side_effect=self.responses(archive, 'sha256:wrong')):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    ACTIONS.download(123, 'snapshot', destination)
            self.assertFalse(destination.exists())

    def test_archive_cannot_write_outside_its_directory(self):
        archive = self.archive('../escaped')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(ACTIONS, 'api', side_effect=self.responses(archive)):
                with self.assertRaisesRegex(ValueError, 'unsafe artifact path'):
                    ACTIONS.download(123, 'snapshot', root / 'out')
            self.assertFalse((root / 'escaped').exists())

    def test_verified_snapshot_is_materialised(self):
        archive = self.archive()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'out'
            with patch.object(ACTIONS, 'api', side_effect=self.responses(archive)):
                ACTIONS.download(123, 'snapshot', destination)
            self.assertEqual(json.loads((destination / 'state.json').read_text()), {'schema': 1})

    def test_multiple_artifacts_from_a_run_share_one_listing(self):
        archive = self.archive()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            indexes = {}
            with patch.object(ACTIONS, 'api', side_effect=[self.responses(archive)[0], archive, archive]) as api:
                ACTIONS.download(123, 'snapshot', root / 'first', indexes)
                ACTIONS.download(123, 'snapshot', root / 'second', indexes)
            listings = [call for call in api.call_args_list if '/artifacts?' in call.args[0]]
            self.assertEqual(len(listings), 1)


class WaveTransport(unittest.TestCase):
    def snapshot(self, root):
        transaction = root / 'transaction'
        transaction.mkdir()
        state = {'commit': SHA, 'wave': 4, 'pending': ['c'], 'arches': ['x86_64', 'aarch64'],
                 'builds': {'a': {'wave': 0}, 'b': {'wave': 3}}}
        context = {'source_sha': SHA, 'source_ref': 'topic', 'root_run': 9, 'pr_number': 85,
                   'runs': {'0': 10, '3': 13}}
        (transaction / 'state.json').write_text(json.dumps(state))
        ACTIONS.save(transaction, context)
        return transaction

    def test_initialisation_keeps_pr_identity_in_transport_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            transaction = self.snapshot(Path(temporary))
            with patch.dict(os.environ, GITHUB_RUN_ID='9'), patch.object(ACTIONS, 'status'), patch.object(ACTIONS, 'describe'):
                ACTIONS.initialise(argparse.Namespace(transaction=transaction, ref='topic', pr_number=85))
            state, context = ACTIONS.read(transaction)
            self.assertEqual(context['pr_number'], 85)
            self.assertNotIn('pr_number', state)

    def test_final_source_bundles_come_from_their_latest_build_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transaction = self.snapshot(root)
            args = argparse.Namespace(transaction=transaction, artifacts=root / 'candidates')
            with patch.object(ACTIONS, 'download') as download:
                ACTIONS.sources(args)
            self.assertEqual([(call.args[0], call.args[1]) for call in download.call_args_list], [
                (10, 'source-w0-a'), (13, 'source-w3-b')])
            self.assertNotIn('runs', json.loads((transaction / 'state.json').read_text()))

    def test_acceptance_batches_cover_each_package_once_on_each_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            transaction = self.snapshot(Path(temporary))
            path = transaction / 'state.json'
            state = json.loads(path.read_text())
            state['builds'] = {f'p{index}': {} for index in range(119)}
            path.write_text(json.dumps(state))
            with patch.object(ACTIONS.subprocess, 'check_output', return_value=SHA), patch.object(ACTIONS, 'outputs') as outputs:
                ACTIONS.describe(argparse.Namespace(transaction=transaction))
            matrix = outputs.call_args.args[0]['matrix']['include']
            self.assertEqual(len(matrix), 60)
            self.assertTrue(all(0 < len(cell['packages']) <= 4 for cell in matrix))
            for arch in state['arches']:
                packages = [package for cell in matrix if cell['arch'] == arch for package in cell['packages']]
                self.assertEqual(sorted(packages), sorted(state['builds']))

    def test_branch_movement_cannot_dispatch_a_different_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            transaction = self.snapshot(Path(temporary))
            with patch.object(ACTIONS.subprocess, 'check_output', return_value='b' * 40 + '\trefs/heads/topic\n'), patch.object(ACTIONS, 'api') as api:
                with self.assertRaisesRegex(ValueError, 'source ref moved'):
                    ACTIONS.dispatch(argparse.Namespace(transaction=transaction))
            api.assert_not_called()

    def test_dispatch_uses_the_saved_ref_and_snapshot_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            transaction = self.snapshot(Path(temporary))
            with patch.dict(os.environ, GITHUB_RUN_ID='14'), patch.object(ACTIONS.subprocess, 'check_output', return_value=SHA + '\trefs/heads/topic\n'), patch.object(ACTIONS, 'api', return_value={'workflow_run_id': 15, 'html_url': 'https://example.invalid/15'}) as api:
                ACTIONS.dispatch(argparse.Namespace(transaction=transaction))
            self.assertEqual(api.call_args_list[0].args[1], {'ref': 'topic', 'inputs': {
                'phase': 'build', 'snapshot_run': '14', 'wave': '4', 'source_sha': SHA, 'pr_number': '85'}})
            status = api.call_args_list[1].args[1]
            self.assertEqual(status['state'], 'pending')
            self.assertEqual(status['target_url'], 'https://example.invalid/15')




class SnapshotReuse(unittest.TestCase):
    def args(self, root):
        return argparse.Namespace(run=13, previous_sha=None, ref='refs/heads/topic', pr_number=85,
                                  output=root / 'previous', artifacts=root / 'artifacts')

    def api(self, path, **kwargs):
        if path == 'actions/runs/13':
            return {'id': 13, 'status': 'completed', 'conclusion': 'success', 'head_sha': SHA}
        return {'artifacts': [{'name': 'transaction-w4', 'expired': False},
                              {'name': 'candidate-pool', 'expired': False}]}

    def download(self, run, name, destination, indexes):
        destination.mkdir(parents=True)
        if name.startswith('transaction-w'):
            (destination / 'state.json').write_text(json.dumps({'commit': SHA, 'pending': []}))
            ACTIONS.save(destination, {'source_sha': SHA, 'source_ref': 'topic', 'pr_number': 85,
                                       'runs': {'3': 13}})

    def test_explicit_snapshot_verifies_pr_identity_and_restores_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary))
            with patch.object(ACTIONS, 'api', side_effect=self.api), \
                 patch.object(ACTIONS, 'download', side_effect=self.download) as download, \
                 patch.object(ACTIONS.subprocess, 'run') as fetch, patch.object(ACTIONS, 'outputs') as outputs:
                ACTIONS.restore(args)
            self.assertEqual([c.args[1] for c in download.call_args_list], ['transaction-w4', 'candidate-pool'])
            self.assertEqual(ACTIONS.read(args.output)[1]['runs'], {'3': 13})
            self.assertIn(SHA, fetch.call_args.args[0])
            outputs.assert_called_once_with({'restored': True})

    def test_another_pr_snapshot_cannot_supply_candidate_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary))
            args.pr_number = 99
            with patch.object(ACTIONS, 'api', side_effect=self.api), \
                 patch.object(ACTIONS, 'download', side_effect=self.download) as download:
                with self.assertRaisesRegex(ValueError, 'another source or pull request'):
                    ACTIONS.restore(args)
            self.assertEqual(download.call_count, 1)
            self.assertFalse(args.output.exists())

    def test_pr_update_discovers_the_previous_commit_without_a_fixed_run_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary))
            args.run, args.previous_sha = None, SHA
            def api(path, **kwargs):
                if path.startswith('actions/runs?'):
                    return {'workflow_runs': [self.api('actions/runs/13')]}
                return self.api(path, **kwargs)
            with patch.object(ACTIONS, 'api', side_effect=api), \
                 patch.object(ACTIONS, 'download', side_effect=self.download), \
                 patch.object(ACTIONS.subprocess, 'run'), patch.object(ACTIONS, 'outputs') as outputs:
                ACTIONS.restore(args)
            outputs.assert_called_once_with({'restored': True})

    def test_new_pr_can_reuse_the_exact_merged_main_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.args(Path(temporary))
            args.run, args.previous_sha, args.base, args.pr_number = None, None, 'origin/main', 99

            def api(path, **kwargs):
                if path.endswith('/pulls'):
                    return [{'head': {'sha': SHA}}]
                if path.startswith('actions/workflows/ci.yml/runs?'):
                    return {'workflow_runs': [self.api('actions/runs/13')]}
                return self.api(path, **kwargs)

            def download(run, name, destination, indexes):
                self.download(run, name, destination, indexes)
                if name.startswith('transaction-w'):
                    path = destination / 'state.json'
                    state = json.loads(path.read_text())
                    state['tree'] = 'c' * 40
                    path.write_text(json.dumps(state))

            with patch.object(ACTIONS, 'api', side_effect=api), \
                    patch.object(ACTIONS, 'download', side_effect=download), \
                    patch.object(ACTIONS.subprocess, 'check_output', return_value='c' * 40), \
                    patch.object(ACTIONS.subprocess, 'run'), patch.object(ACTIONS, 'outputs') as outputs:
                ACTIONS.restore(args)
            outputs.assert_called_once_with({'restored': True})


class CandidateSelection(unittest.TestCase):
    def test_string_outputs_are_literal_and_collections_remain_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'outputs'
            with patch.dict(os.environ, GITHUB_OUTPUT=str(output)):
                ACTIONS.outputs({'source_sha': SHA, 'packages': ['a'], 'skip': False})
            self.assertEqual(output.read_text(), f'source_sha={SHA}\npackages=["a"]\nskip=false\n')

    def args(self):
        return argparse.Namespace(commit='b' * 40, run=13, pr_number=None)

    def api(self, path, body=None):
        if path == 'actions/runs/13':
            return {'id': 13, 'path': '.github/workflows/ci.yml', 'repository': {'full_name': 'owner/repo'},
                    'status': 'completed', 'conclusion': 'success', 'head_sha': SHA}
        if path.endswith('/pulls'):
            return [{'head': {'sha': SHA}}]
        if path.startswith('actions/workflows/ci.yml/runs?'):
            return {'workflow_runs': [self.api('actions/runs/13')] if SHA in path else []}
        if path.startswith('actions/runs/13/artifacts?'):
            return {'artifacts': [{'name': 'release-candidate', 'expired': False}]}
        if path.startswith('commits/'):
            return {'commit': {'tree': {'sha': 'c' * 40}}}
        raise AssertionError(path)

    def test_successful_candidate_survives_rebase_with_the_same_tree(self):
        with patch.dict(os.environ, GITHUB_REPOSITORY='owner/repo'), \
                patch.object(ACTIONS, 'api', side_effect=self.api), patch.object(ACTIONS, 'outputs') as outputs:
            ACTIONS.candidate(self.args())
        outputs.assert_called_once_with({'run': 13, 'source_sha': SHA, 'skip': False})

    def test_merged_pr_discovers_its_original_head_artifacts(self):
        args = self.args()
        args.run = None
        with patch.dict(os.environ, GITHUB_REPOSITORY='owner/repo'), \
                patch.object(ACTIONS, 'api', side_effect=self.api), patch.object(ACTIONS, 'outputs') as outputs:
            ACTIONS.candidate(args)
        outputs.assert_called_once_with({'run': 13, 'source_sha': SHA, 'skip': False})

    def test_expired_wrong_tree_failed_and_other_workflow_runs_cannot_release(self):
        for error in ('expired', 'tree', 'failed', 'workflow', 'repository'):
            def api(path, body=None):
                result = self.api(path, body)
                if error == 'expired' and '/artifacts?' in path:
                    result['artifacts'][0]['expired'] = True
                if error == 'tree' and path == f'commits/{SHA}':
                    result['commit']['tree']['sha'] = 'd' * 40
                if path == 'actions/runs/13':
                    if error == 'failed': result['conclusion'] = 'failure'
                    if error == 'workflow': result['path'] = '.github/workflows/other.yml'
                    if error == 'repository': result['repository']['full_name'] = 'fork/repo'
                return result
            with self.subTest(error=error), patch.dict(os.environ, GITHUB_REPOSITORY='owner/repo'), \
                    patch.object(ACTIONS, 'api', side_effect=api), patch.object(ACTIONS, 'outputs') as outputs:
                with self.assertRaisesRegex(ValueError, 'no accepted candidate'):
                    ACTIONS.candidate(self.args())
                outputs.assert_not_called()

    def test_reviewed_fork_sha_cannot_move_before_import(self):
        pull = {'state': 'open', 'base': {'repo': {'full_name': 'owner/repo'}}, 'head': {'sha': SHA}}
        with patch.dict(os.environ, GITHUB_REPOSITORY='owner/repo'), patch.object(ACTIONS, 'api', return_value=pull) as api:
            with self.assertRaisesRegex(ValueError, 'moved since review'):
                ACTIONS.import_pr(argparse.Namespace(number=42, sha='b' * 40))
        self.assertEqual(api.call_count, 1)


if __name__ == '__main__':
    unittest.main()
