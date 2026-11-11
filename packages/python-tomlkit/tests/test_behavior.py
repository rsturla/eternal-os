import datetime
from pathlib import Path
import unittest

import tomlkit
from tomlkit.exceptions import ParseError


class TomlTests(unittest.TestCase):
    def setUp(self):
        self.source = Path(__file__).with_name("document.toml").read_text()
        self.document = tomlkit.parse(self.source)

    def test_lossless_roundtrip(self):
        self.assertEqual(tomlkit.dumps(self.document), self.source)

    def test_types_and_nested_values(self):
        self.assertEqual(self.document["answer"], 42)
        self.assertEqual(self.document["ports"], [8000, 8001])
        self.assertEqual(self.document["date"], datetime.date(2026, 11, 11))
        self.assertEqual(
            self.document["instant"],
            datetime.datetime(2026, 11, 11, 12, 34, 56, tzinfo=datetime.timezone.utc),
        )
        self.assertTrue(self.document["enabled"])
        self.assertEqual(self.document["server"]["host"], "localhost")
        self.assertEqual(
            [item["name"] for item in self.document["items"]], ["first", "second"]
        )

    def test_edit_preserves_other_formatting(self):
        self.document["answer"] = 43
        expected = self.source.replace(
            "answer = 42 # inline note", "answer = 43 # inline note"
        )
        self.assertEqual(tomlkit.dumps(self.document), expected)

    def test_table_and_array_mutation(self):
        self.document["items"][1]["name"] = "updated"
        self.document["ports"].append(9000)
        self.document["server"]["workers"] = 4
        del self.document["title"]
        decoded = tomlkit.parse(tomlkit.dumps(self.document)).unwrap()
        self.assertEqual(decoded["ports"], [8000, 8001, 9000])
        self.assertEqual(decoded["items"][1], {"name": "updated"})
        self.assertEqual(decoded["server"], {"host": "localhost", "workers": 4})
        self.assertNotIn("title", decoded)

    def test_build_and_escape_document(self):
        doc = tomlkit.document()
        doc.add(tomlkit.comment("generated fixture"))
        doc.add("value", 'quote " and newline\n and Unicode ü')
        doc.add("table", tomlkit.table().add("answer", 42))
        text = tomlkit.dumps(doc)
        self.assertIn("# generated fixture", text)
        self.assertEqual(
            tomlkit.parse(text).unwrap(),
            {"value": 'quote " and newline\n and Unicode ü', "table": {"answer": 42}},
        )

    def test_invalid_toml_and_duplicate_keys(self):
        for source in [
            "answer = [\n",
            "answer = 1\nanswer = 2\n",
            'value = "unterminated\n',
        ]:
            with self.subTest(source=source), self.assertRaises(ParseError):
                tomlkit.parse(source)


if __name__ == "__main__":
    import importlib.metadata
    import sys

    stream, distribution, version = sys.argv[1:]
    assert sys.version_info[:2] == tuple(map(int, stream.split(".")))
    assert importlib.metadata.version(distribution) == version
    unittest.main(argv=[sys.argv[0]], verbosity=2)
