"""Round-5 gate tests (offline): wordlist gate, lang detection, pipeline flow."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from asr_correct.config import Config                     # noqa: E402
from asr_correct.gates import WordlistGate               # noqa: E402
from asr_correct.pipeline import run                     # noqa: E402
from asr_correct.segment import lang_of, split_sentences  # noqa: E402


class TestEnGate(unittest.TestCase):
    def setUp(self):
        self.g = WordlistGate()

    def test_nonword_flagged(self):
        flagged, marks, _ = self.g.check("After proceedcing a few miles")
        self.assertTrue(flagged)
        self.assertEqual(marks[0]["word"], "proceedcing")

    def test_clean_not_flagged(self):
        flagged, _, _ = self.g.check("hello world today is fine")
        self.assertFalse(flagged)

    def test_short_words_ignored(self):
        flagged, _, _ = self.g.check("ok mr smith the fox")
        self.assertFalse(flagged)


class TestLangOf(unittest.TestCase):
    def test_zh(self):
        self.assertEqual(lang_of("今天天气很好。"), "zh")

    def test_en(self):
        self.assertEqual(lang_of("Hello there my friend"), "en")


class TestPipelineWithFakeGate(unittest.TestCase):
    """Gate blocks unflagged sentences -> zero LLM calls for them."""

    def test_gated_sentence_skips_llm(self):
        import asr_correct.pipeline as pl
        import asr_correct.correct as correct

        class FakeGate:
            def __init__(self, flag_fn):
                self.flag_fn = flag_fn
            def check(self, text):
                return self.flag_fn(text), [], 1.0

        zh_gate = FakeGate(lambda t: "候" in t)      # only flags the dirty sentence
        en_gate = WordlistGate()
        calls = []

        def fake_correct(sentence, cfg, log=print, hint=None):
            calls.append(sentence)
            return {"orig": sentence, "final": sentence.replace("候", "后"),
                    "edits": [(9, "候", "后")], "guards": [], "calls": 2,
                    "models": ["d41n"], "lat": [1.0, 1.0], "pass2": True}

        orig_build = pl.build_gates
        orig_correct = correct.correct_sentence
        pl.build_gates = lambda cfg, log=print: (zh_gate, en_gate)
        pl.correct_sentence = fake_correct
        try:
            text = "财政金融政策紧随其候而来。这句话完全正确不需要任何修改。"
            res = run(text=text, cfg=Config(verify_enabled=True), log=lambda *_: None)
        finally:
            pl.build_gates = orig_build
            pl.correct_sentence = orig_correct

        self.assertEqual(res["stats"]["gated_out"], 1)
        self.assertEqual(len(calls), 1)               # only the dirty sentence called LLM
        self.assertIn("后", res["corrected_text"])
        self.assertNotIn("候", res["corrected_text"])


if __name__ == "__main__":
    unittest.main()
