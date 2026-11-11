import subprocess
import sys
import unittest

from trove_classifiers import classifiers, deprecated_classifiers


class ClassifierTests(unittest.TestCase):
    def test_known_production_classifiers(self):
        expected = {
            "Development Status :: 5 - Production/Stable",
            "License :: OSI Approved :: MIT License",
            "Operating System :: POSIX :: Linux",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3 :: Only",
            "Topic :: Software Development :: Libraries :: Python Modules",
        }
        self.assertLessEqual(expected, classifiers)
        self.assertNotIn("Programming Language :: Imaginary Language", classifiers)

    def test_supported_python_streams(self):
        for version in ["3.11", "3.12", "3.13", "3.14", "3.15"]:
            with self.subTest(version=version):
                self.assertIn(
                    f"Programming Language :: Python :: {version}", classifiers
                )

    def test_deprecation_replacement_is_available(self):
        old = "Natural Language :: Ukranian"
        self.assertEqual(deprecated_classifiers[old], ["Natural Language :: Ukrainian"])
        self.assertNotIn(old, classifiers)
        self.assertIn("Natural Language :: Ukrainian", classifiers)
        for old, replacements in deprecated_classifiers.items():
            with self.subTest(classifier=old):
                self.assertNotIn(old, classifiers)
                self.assertLessEqual(set(replacements), classifiers)

    def test_cli_matches_canonical_data(self):
        result = subprocess.run(
            [sys.executable, "-m", "trove_classifiers"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(set(result.stdout.splitlines()), classifiers)
        self.assertEqual(len(result.stdout.splitlines()), len(classifiers))
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    import importlib.metadata
    import sys

    stream, distribution, version = sys.argv[1:]
    assert sys.version_info[:2] == tuple(map(int, stream.split(".")))
    assert importlib.metadata.version(distribution) == version
    unittest.main(argv=[sys.argv[0]], verbosity=2)
