#!/usr/bin/env python3
"""Screen candidates with real ASR; keep only clips where SenseVoice actually erred.

Effectiveness hinge: a correction experiment needs clips WITH errors. Clean read-aloud
corpora give high accuracy to SenseVoice, so we scan until we hit `--need` error clips
per language. Every accepted clip stores its ground-truth bad positions (alignment
vs reference) for later detection P/R.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_ec import sf_asr, norm_zh, norm_en, bad_positions, err_rate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/work")
    ap.add_argument("--out", default=None)
    ap.add_argument("--need", type=int, default=5, help="error clips per language")
    ap.add_argument("--budget", type=int, default=60, help="max clips scanned per language")
    args = ap.parse_args()
    out = args.out or os.path.join(args.work, "manifest.smoke.jsonl")

    rows = [json.loads(l) for l in open(os.path.join(args.work, "manifest.all.jsonl"), encoding="utf-8")]
    accepted = {"zh": [], "en": []}
    with open(os.path.join(args.work, "screen_log.jsonl"), "a", encoding="utf-8") as logf:
        for lang in ["zh", "en"]:
            scanned = 0
            for r in [x for x in rows if x["lang"] == lang]:
                if len(accepted[lang]) >= args.need or scanned >= args.budget:
                    break
                scanned += 1
                try:
                    raw = sf_asr(r["wav"])
                except Exception as e:  # noqa: BLE001
                    print("ASR FAIL", r["id"], repr(e)[:120])
                    continue
                if lang == "zh":
                    hyp, ref = norm_zh(raw), norm_zh(r["ref"])
                    h_seq, r_seq = list(hyp), list(ref)
                else:
                    hyp, ref = norm_en(raw), norm_en(r["ref"])
                    h_seq, r_seq = hyp.split(), ref.split()
                if not h_seq:
                    continue
                e = err_rate(r_seq, h_seq)
                bad = bad_positions(h_seq, r_seq)
                rec = {"id": r["id"], "wav": r["wav"], "lang": lang, "ref": ref,
                       "hyp_raw": raw, "hyp": hyp, "err_rate": round(e, 4),
                       "bad_positions": bad}
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                logf.flush()
                mark = "HIT " if e > 0 else "    "
                print(f"{mark}{lang} scanned={scanned} {r['id']} err={e:.3f} bad={bad}")
                if e > 0 and len(accepted[lang]) < args.need:
                    accepted[lang].append(rec)
                time.sleep(0.2)

    with open(out, "w", encoding="utf-8") as f:
        for lang in ["zh", "en"]:
            for rec in accepted[lang]:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("accepted:", {k: len(v) for k, v in accepted.items()}, "->", out)


if __name__ == "__main__":
    main()
