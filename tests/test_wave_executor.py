"""The coordinator must reject failed or incomplete execution adapters."""

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('waves', ROOT / 'scripts/build-waves.py')
WAVES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WAVES)


class WaveExecutor(unittest.TestCase):
    def test_empty_transaction_does_not_build_accept_or_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / 'state.json'
            state.write_text(json.dumps({'pending': [], 'builds': {}}))
            args = argparse.Namespace(state=state, artifacts=root / 'artifacts', output=root / 'candidate',
                                      cache=root / 'cache', rpmx='unused', max_waves=8)
            WAVES.build(args, executor=object())
            self.assertEqual(set(root.iterdir()), {state})

    def test_failed_or_incomplete_adapter_cannot_advance_or_accept(self):
        for failure in (True, False):
            with self.subTest(worker_failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                state = root / 'state.json'
                state.write_text(json.dumps({'pending': ['provider'], 'wave': 0, 'interfaces': {}, 'builds': {}}))
                original = state.read_bytes()
                calls = []

                class Executor:
                    def build_wave(self, state_path):
                        calls.append(('build', state_path.read_bytes()))
                        if failure:
                            raise RuntimeError('worker failed')
                        # A worker returning without its RPM artifacts must
                        # fail validation just as a failed worker does.

                    def accept(self, state_path, repository):
                        calls.append(('accept', state_path.read_bytes()))

                args = argparse.Namespace(state=state, artifacts=root / 'artifacts', output=root / 'candidate',
                                          cache=root / 'cache', rpmx='unused', max_waves=8)
                with self.assertRaises(RuntimeError if failure else FileNotFoundError):
                    WAVES.build(args, executor=Executor())
                self.assertEqual(calls, [('build', original)])
                self.assertEqual(state.read_bytes(), original)
                self.assertFalse(args.output.exists())


if __name__ == '__main__':
    unittest.main()
