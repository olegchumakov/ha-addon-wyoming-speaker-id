"""Tests for the language list advertised to Home Assistant (never empty because the upstream was slow)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace as NS

from speaker_id.languages import FILE_NAME, Languages, collect, parse

URI = "tcp://core-whisper:10300"


def _info(*models, installed=True):
    return NS(asr=[NS(installed=installed, models=[NS(installed=True, languages=list(m)) for m in models])])


class CollectTest(unittest.TestCase):
    def test_collects_sorted_unique(self):
        self.assertEqual(collect(_info(["ru", "en"], ["en", "de"])), ["de", "en", "ru"])

    def test_empty_while_starting(self):
        self.assertEqual(collect(NS(asr=[])), [])
        self.assertEqual(collect(_info([])), [])
        self.assertEqual(collect(_info(["en"], installed=False)), [])


class ParseTest(unittest.TestCase):
    def test_separators_and_duplicates(self):
        self.assertEqual(parse("en, de;pt-BR  en"), ["en", "de", "pt-BR"])

    def test_empty_and_invalid(self):
        self.assertEqual(parse(None), [])
        self.assertEqual(parse(""), [])
        with self.assertLogs("speaker_id", "WARNING"):
            self.assertEqual(parse("en, english!, x"), ["en"])


class LanguagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_nothing_known_means_empty(self):
        langs = Languages(self.dir, URI)
        self.assertEqual(langs.current, [])
        self.assertIsNone(langs.source)

    def test_fallback_until_upstream_answers(self):
        langs = Languages(self.dir, URI, "de, en")
        self.assertEqual((langs.current, langs.source), (["de", "en"], "setting"))
        self.assertTrue(langs.set_live(["fr"]))
        self.assertEqual((langs.current, langs.source), (["fr"], "live"))

    def test_empty_upstream_answer_is_ignored(self):
        langs = Languages(self.dir, URI, "en")
        self.assertFalse(langs.set_live([]))
        self.assertEqual((langs.current, langs.source), (["en"], "setting"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, FILE_NAME)))

    def test_saved_list_survives_restart(self):
        Languages(self.dir, URI).set_live(["ru", "en"])
        after_restart = Languages(self.dir, URI, "de")
        self.assertEqual((after_restart.current, after_restart.source), (["en", "ru"], "saved"))

    def test_saved_list_of_other_upstream_is_not_used(self):
        Languages(self.dir, "tcp://other:10300").set_live(["en"])
        self.assertEqual(Languages(self.dir, URI).current, [])

    def test_broken_saved_file(self):
        with open(os.path.join(self.dir, FILE_NAME), "w", encoding="utf-8") as f:
            f.write("{not json")
        with self.assertLogs("speaker_id", "WARNING"):
            self.assertEqual(Languages(self.dir, URI).current, [])
        with open(os.path.join(self.dir, FILE_NAME), "w", encoding="utf-8") as f:
            json.dump({"upstream_uri": URI, "languages": "en"}, f)
        self.assertEqual(Languages(self.dir, URI).current, [])


if __name__ == "__main__":
    unittest.main()
