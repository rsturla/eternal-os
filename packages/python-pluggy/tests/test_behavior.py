import unittest

import pluggy

hookspec = pluggy.HookspecMarker("eternal")
hookimpl = pluggy.HookimplMarker("eternal")


class Specification:
    @hookspec
    def calculate(self, value):
        """Return a transformed value."""

    @hookspec(firstresult=True)
    def choose(self, value):
        """Return the first non-None value."""

    @hookspec(historic=True)
    def notify(self, value):
        """Replay notifications to plugins registered later."""


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.manager = pluggy.PluginManager("eternal")
        self.manager.add_hookspecs(Specification)

    def test_ordered_hooks_and_unregister(self):
        class First:
            @hookimpl(tryfirst=True)
            def calculate(self, value):
                return value + 2

        class Last:
            @hookimpl(trylast=True)
            def calculate(self, value):
                return value + 3

        first, last = First(), Last()
        self.manager.register(last, "last")
        self.manager.register(first, "first")
        self.assertEqual(self.manager.hook.calculate(value=40), [42, 43])
        self.assertIs(self.manager.unregister(first), first)
        self.assertFalse(self.manager.has_plugin("first"))
        self.assertEqual(self.manager.hook.calculate(value=40), [43])

    def test_wrapper_changes_collected_results(self):
        class Ordinary:
            @hookimpl
            def calculate(self, value):
                return value + 1

        class Wrapper:
            @hookimpl(wrapper=True)
            def calculate(self, value):
                result = yield
                return [item * 2 for item in result]

        self.manager.register(Ordinary())
        self.manager.register(Wrapper())
        self.assertEqual(self.manager.hook.calculate(value=20), [42])

    def test_first_result_ignores_none(self):
        class Fallback:
            @hookimpl(trylast=True)
            def choose(self, value):
                return value + 2

        class Empty:
            @hookimpl(tryfirst=True)
            def choose(self, value):
                return None

        self.manager.register(Fallback())
        self.manager.register(Empty())
        self.assertEqual(self.manager.hook.choose(value=40), 42)

    def test_historic_call_is_replayed(self):
        seen = []
        self.manager.hook.notify.call_historic(kwargs={"value": 42})

        class Late:
            @hookimpl
            def notify(self, value):
                seen.append(value)

        self.manager.register(Late())
        self.assertEqual(seen, [42])
        self.manager.hook.notify.call_historic(kwargs={"value": 43})
        self.assertEqual(seen, [42, 43])

    def test_duplicate_registration_and_blocking(self):
        self.manager.register(object(), "registered")
        with self.assertRaises(ValueError):
            self.manager.register(object(), "registered")
        self.manager.set_blocked("blocked")
        self.assertIsNone(self.manager.register(object(), "blocked"))
        self.assertTrue(self.manager.is_blocked("blocked"))
        self.assertTrue(self.manager.unblock("blocked"))
        self.assertEqual(self.manager.register(object(), "blocked"), "blocked")

    def test_invalid_hook_signature_is_rejected(self):
        class Invalid:
            @hookimpl
            def calculate(self, unknown_argument):
                return unknown_argument

        with self.assertRaises(pluggy.PluginValidationError):
            self.manager.register(Invalid())

    def test_hook_exceptions_propagate(self):
        class Broken:
            @hookimpl
            def calculate(self, value):
                raise RuntimeError("fixture hook failed")

        self.manager.register(Broken())
        with self.assertRaisesRegex(RuntimeError, "fixture hook failed"):
            self.manager.hook.calculate(value=42)


if __name__ == "__main__":
    import importlib.metadata
    import sys

    stream, distribution, version = sys.argv[1:]
    assert sys.version_info[:2] == tuple(map(int, stream.split(".")))
    assert importlib.metadata.version(distribution) == version
    unittest.main(argv=[sys.argv[0]], verbosity=2)
