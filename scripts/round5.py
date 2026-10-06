#!/usr/bin/env python3
"""Round 5: CSC gate (Layer-0) x champion two-pass correction.

Questions this round answers:
  1. Does a local pinyin-aware CSC detector (MacBERT4CSC) as a cheap gate
     cut LLM calls without losing correction power?
  2. Which gate threshold: recall-first (t=0.5) vs cost-first (t=0.9)?
  3. Do gate hints (suspicious chars fed into pass-1) help or hurt? (G4)
  4. English wordlist gate: free non-word catcher.

Conditions (all use asr_correct.correct_sentence = production code,
d41n two-pass with skip-verify-when-no-edit):
  G0  no gate (today's production cost, includes skip-verify saving)
  G1  CSC@0.5 (zh) + wordlist (en)
  G2  CSC@0.9 (zh) + wordlist (en)
  G4  CSC@0.5 + hints into pass-1 prompt

Test set: experiments/round4/manifest.round4.jsonl (10 dirty + 10 clean).
Baseline reference: R4 E3-d41 (always-verify, no gate).
"""
import argparse
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from asr_correct.config import Config                      # noqa: E402
from asr_correct.correct import correct_sentence          # noqa: E402

CSC_MODEL = "shibing624/macbert4csc-base-chinese"


class CscGate:
    """MacBERT4CSC as detector: positions where argmax != input are errors."""

    def __init__(self, threshold):
        import torch  # noqa: F401
        from transformers import BertForMaskedLM, BertTokenizerFast
        self.tok = BertTokenizerFast.from_pretrained(CSC_MODEL)
        self.model = BertForMaskedLM.from_pretrained(CSC_MODEL)
        self.model.eval()
        self.th = threshold

    def check(self, text):
        import torch
        t0 = time.time()
        enc = self.tok(text, return_tensors="pt", truncation=True, max_length=128)
        with torch.no_grad():
            logits = self.model(**enc).logits
        probs = torch.softmax(logits, -1)[0]
        ids = enc["input_ids"][0]
        marks = []
        for pos in range(1, int((enc["attention_mask"][0]).sum()) - 1):
            conf, pred = probs[pos].max(0)
            if int(pred) != int(ids[pos]) and float(conf) >= self.th:
                marks.append({"char": self.tok.decode(ids[pos]),
                              "suggest": self.tok.decode(pred),
                              "conf": round(float(conf), 3)})
        return (len(marks) > 0), marks, round((time.time() - t0) * 1000, 1)


class WordlistGate:
    """English non-word gate: pyspellchecker (pure python, no model)."""

    def __init__(self, min_len=4):
        from spellchecker import SpellChecker
        self.sc = SpellChecker()
        self.min_len = min_len

    def check(self, text):
        t0 = time.time()
        words = [w.strip(".,!?;:'\"()-").lower() for w in text.split()]
        words = [w for w in words if len(w) >= self.min_len and w.isalpha()]
        unknown = sorted(self.sc.unknown(words))
        marks = [{"word": w} for w in unknown]
        return (len(unknown) > 0), marks, round((time.time() - t0) * 1000, 1)


def normalize(text, lang):
    from asr_ec import norm_zh, norm_en
    return norm_zh(text) if lang == "zh" else norm_en(text)


def run_condition(name, clips, repeats, cfg, gate_zh, gate_en, hints=False):
    records = []
    for clip in clips:
        for rep in range(1, repeats + 1):
            lang, dirty = clip["lang"], clip.get("dirty", True)
            t0 = time.time()
            gate = gate_zh if lang == "zh" else gate_en
            g_ms, flagged, marks = 0, True, []
            if gate is not None:
                flagged, marks, g_ms = gate.check(clip["hyp_raw"])
            if flagged:
                hint = marks if (hints and marks) else None
                r = correct_sentence(clip["hyp_raw"], cfg,
                                     log=lambda *_: None, hint=hint)
            else:
                r = {"final": clip["hyp_raw"], "edits": [], "guards": [],
                     "calls": 0, "models": [], "lat": [], "pass2": False}
            in_n = normalize(clip["hyp_raw"], lang)
            out_n = normalize(r["final"], lang)
            ref_n = normalize(clip["ref"], lang)
            i_seq = list(in_n) if lang == "zh" else in_n.split()
            o_seq = list(out_n) if lang == "zh" else out_n.split()
            r_seq = list(ref_n) if lang == "zh" else ref_n.split()
            from asr_ec import err_rate
            records.append({
                "id": clip["id"], "lang": lang, "dirty": dirty, "repeat": rep,
                "flagged": flagged, "gate_ms": g_ms,
                "err_before": round(err_rate(r_seq, i_seq), 4),
                "err_after": round(err_rate(r_seq, o_seq), 4),
                "calls": r.get("calls", 0), "lat": r.get("lat", []),
                "wall": round(time.time() - t0, 2),
                "marks": marks[:6],
            })
    return records


def summarize(records):
    dirty = [r for r in records if r["dirty"]]
    clean = [r for r in records if not r["dirty"]]

    def m(xs):
        return round(statistics.mean(xs), 4) if xs else None

    lats = sorted(l for r in records for l in (r.get("lat") or []))
    return {
        "n": len(records),
        "dirty_err": m([r["err_before"] for r in dirty]),
        "dirty_err_after": m([r["err_after"] for r in dirty]),
        "dirty_worsened": sum(1 for r in dirty if r["err_after"] > r["err_before"]),
        "clean_damage": sum(1 for r in clean if r["err_after"] > 0),
        "dirty_flag_recall": round(sum(1 for r in dirty if r["flagged"]) / len(dirty), 3) if dirty else None,
        "clean_flag_rate": round(sum(1 for r in clean if r["flagged"]) / len(clean), 3) if clean else None,
        "llm_calls": sum(r["calls"] for r in records),
        "calls_per_sent": round(sum(r["calls"] for r in records) / len(records), 3),
        "gate_ms_mean": m([r["gate_ms"] for r in records]),
        "lat_p50": lats[len(lats) // 2] if lats else None,
    }


def md_table(rows):
    out = ["| 条件 | 脏句错误率 | 恶化 | 净损 | 脏句召回 | 净句误标 | LLM调用 | 调用/句 | 门控ms |",
           "|---|---|---|---|---|---|---|---|---|"]
    for name, s in rows:
        if s is None:
            out.append(f"| {name} | SKIP | | | | | | | |")
            continue
        out.append(
            f"| {name} | {s['dirty_err']} → {s['dirty_err_after']} "
            f"({(s['dirty_err_after'] - s['dirty_err']) / s['dirty_err'] * 100:+.0f}%) "
            f"| {s['dirty_worsened']} | {s['clean_damage']} "
            f"| {s['dirty_flag_recall']} | {s['clean_flag_rate']} "
            f"| {s['llm_calls']} | {s['calls_per_sent']} | {s['gate_ms_mean']} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()
    clips = [json.loads(l) for l in open(args.manifest, encoding="utf-8")]
    cfg = Config()
    print("clips:", len(clips), flush=True)

    gates = {"g1": None, "g2": None}
    try:
        print("loading CSC model:", CSC_MODEL, flush=True)
        gates["g1"] = CscGate(0.5)
        gates["g2"] = CscGate(0.9)
        print("CSC loaded", flush=True)
    except Exception as e:  # noqa: BLE001
        print("CSC unavailable (no torch/transformers?):", repr(e)[:120], flush=True)
    wg = WordlistGate()

    conds = [("G0 无门控", None, None, False),
             ("G1 CSC@0.5+词表", gates["g1"], wg, False),
             ("G2 CSC@0.9+词表", gates["g2"], wg, False),
             ("G4 CSC@0.5+提示注入", gates["g1"], wg, True)]
    rows = []
    all_records = {}
    for name, gz, ge, hints in conds:
        key = name.split()[0]
        if key != "G0" and gz is None:
            rows.append((name, None))
            continue
        print("== running", name, flush=True)
        recs = run_condition(key, clips, args.repeats, cfg, gz, ge, hints)
        s = summarize(recs)
        rows.append((name, s))
        all_records[key] = {"summary": s, "records": recs}
        print(json.dumps(s, ensure_ascii=False), flush=True)

    # zh / en split for the winner-ish view
    for lang in ["zh", "en"]:
        sub = []
        for key in all_records:
            rs = [r for r in all_records[key]["records"] if r["lang"] == lang]
            if rs:
                sub.append((f"{key}({lang})", summarize(rs)))
        if sub:
            rows.extend(sub)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "round5.json"), "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=1)
    lines = ["# Round 5：CSC 门控 × 冠军两遍流", "",
             "同 R4 考卷（10 脏 + 10 净）。参考基线：R4 E3-d41 无门控 -62%、"
             "R4 口径 2 调用/句（无 skip-verify 优化）。", "", md_table(rows)]
    with open(os.path.join(args.out, "round5-summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
