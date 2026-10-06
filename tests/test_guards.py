"""Offline unit tests (no network): guards, segmentation, alignment.

Run: python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from asr_correct.config import Config                    # noqa: E402
from asr_correct.correct import guard, edits_between     # noqa: E402
from asr_correct.segment import split_sentences, windows  # noqa: E402
from asr_correct.asr import _greedy_cutpoints            # noqa: E402


class TestGuard(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_ok_single_edit(self):
        ok, _ = guard("财政金融政策紧随其候而来",
                      "财政金融政策紧随其后而来", self.cfg)
        self.assertTrue(ok)

    def test_empty_rejected(self):
        ok, why = guard("一句话测试", "", self.cfg)
        self.assertFalse(ok)
        self.assertEqual(why, "empty")

    def test_deletion_rejected(self):
        ok, why = guard("这句转写一共有十个字的内容呀",
                        "短句", self.cfg)
        self.assertFalse(ok)
        self.assertIn("deletion", why)

    def test_rewrite_rejected(self):
        ok, why = guard("短句", "这句话被模型大幅扩写成完全不同的长句子内容", self.cfg)
        self.assertFalse(ok)
        self.assertIn("rewrite", why)

    def test_edit_budget(self):
        long_sent = "而" * 40
        rewritten = "了" * 40
        ok, why = guard(long_sent, rewritten, self.cfg)
        self.assertFalse(ok)


class TestEdits(unittest.TestCase):
    def test_substitution(self):
        e = edits_between("开会", "开汇")
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0][1], "会")

    def test_clean(self):
        self.assertEqual(edits_between("一样", "一样"), [])


class TestSegment(unittest.TestCase):
    def test_zh_split(self):
        s = split_sentences("今天开会。明天放假！后天继续")
        self.assertEqual(len(s), 3)

    def test_zh_long_hard_split(self):
        s = split_sentences("字" * 200, max_chars=80)
        self.assertEqual(len(s), 3)  # 200/80 -> 3 parts

    def test_en_split(self):
        s = split_sentences("Hello there friend. How are you today?")
        self.assertEqual(len(s), 2)

    def test_windows_single(self):
        w = list(windows([(0, "a"), (1, "b")], size=1))
        self.assertEqual([e for e, _ in w], [[0], [1]])

    def test_windows_context(self):
        w = list(windows([(0, "a"), (1, "b"), (2, "c"), (3, "d")], size=3, overlap=1))
        editable = [e for e, _ in w]
        self.assertIn([1], editable)  # middle sentence editable


class TestChunking(unittest.TestCase):
    def test_greedy(self):
        # dur=120, max=60: single cut at 62 would leave a 62s chunk (invalid),
        # so the correct answer is silence cuts at both 30 and 62 -> 3 chunks.
        cuts = _greedy_cutpoints([30.0, 62.0], 120.0, 60.0)
        self.assertEqual(cuts, [30.0, 62.0])

    def test_greedy_fallback(self):
        cuts = _greedy_cutpoints([], 130.0, 60.0)
        self.assertEqual(len(cuts), 2)  # fixed cuts at 60 and 120


if __name__ == "__main__":
    unittest.main()
