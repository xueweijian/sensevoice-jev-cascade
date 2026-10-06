"""Layer-0 gates (round-5 champion addition).

zh: MacBERT4CSC — pinyin-aware Chinese spelling checker, per-char error prob
en: pyspellchecker — non-word dictionary lookup (no model at all)

Round-5 measured (same 20-clip protocol as R4 champion):
  LLM calls 1.45 -> 0.65 per sentence (-55%), final err identical,
  worsened clauses 1 -> 0, clean clips zero damage, gate cost 32ms/sentence.
Thresholds 0.5 vs 0.9 indistinguishable (CSC confidences saturate);
hints into pass-1 add nothing (G4 == G1).

Soft dependency: torch/transformers only for the zh gate; if missing the
pipeline degrades to the en gate + a loud warning.
"""
import json

CSC_MODEL = "shibing624/macbert4csc-base-chinese"


class CscGate:
    """zh: positions where the CSC argmax != input char are suspicious."""

    def __init__(self, threshold=0.5):
        from transformers import BertForMaskedLM, BertTokenizerFast
        self.tok = BertTokenizerFast.from_pretrained(CSC_MODEL)
        self.model = BertForMaskedLM.from_pretrained(CSC_MODEL)
        self.model.eval()
        self.th = threshold

    def check(self, text):
        """-> (flagged, marks, ms). marks = [{char, suggest, conf}]."""
        import time

        import torch
        t0 = time.time()
        enc = self.tok(text, return_tensors="pt", truncation=True, max_length=128)
        with torch.no_grad():
            logits = self.model(**enc).logits
        probs = torch.softmax(logits, -1)[0]
        ids = enc["input_ids"][0]
        marks = []
        for pos in range(1, int(enc["attention_mask"][0].sum()) - 1):
            conf, pred = probs[pos].max(0)
            if int(pred) != int(ids[pos]) and float(conf) >= self.th:
                marks.append({"char": self.tok.decode(ids[pos]),
                              "suggest": self.tok.decode(pred),
                              "conf": round(float(conf), 3)})
        return (len(marks) > 0), marks, round((time.time() - t0) * 1000, 1)


class WordlistGate:
    """en: flag sentences containing unknown non-trivial words."""

    def __init__(self, min_len=4):
        from spellchecker import SpellChecker
        self.sc = SpellChecker()
        self.min_len = min_len

    def check(self, text):
        import time

        t0 = time.time()
        words = [w.strip(".,!?;:'\"()-").lower() for w in text.split()]
        words = [w for w in words if len(w) >= self.min_len and w.isalpha()]
        unknown = sorted(self.sc.unknown(words))
        return (len(unknown) > 0), [{"word": w} for w in unknown], \
            round((time.time() - t0) * 1000, 1)


def build_gates(cfg, log=print):
    """-> (zh_gate, en_gate); either may be None (degraded)."""
    zh_gate = en_gate = None
    if not getattr(cfg, "gate_enabled", True):
        return None, None
    try:
        zh_gate = CscGate(cfg.gate_threshold)
        log("[gate] zh: MacBERT4CSC loaded")
    except Exception as e:  # noqa: BLE001
        log(f"[gate] zh gate unavailable ({repr(e)[:100]}), zh sentences all pass")
    try:
        en_gate = WordlistGate(cfg.gate_en_min_len)
        log("[gate] en: wordlist gate active")
    except Exception as e:  # noqa: BLE001
        log(f"[gate] en gate unavailable ({repr(e)[:100]})")
    return zh_gate, en_gate


def gate_marks_json(marks):
    return json.dumps(marks, ensure_ascii=False)
