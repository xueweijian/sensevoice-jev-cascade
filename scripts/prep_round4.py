#!/usr/bin/env python3
"""Round 4 prep: screen CLEAN clips (ASR err==0) + merge archived dirty clips
-> manifest.round4.jsonl (10 dirty + 10 clean). Also emits pinyin_index.json."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_ec import sf_asr, norm_zh, norm_en, err_rate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DIRTY_MANIFEST = os.path.join(HERE, "..", "experiments", "round1-ci-v4flash",
                              "manifest.smoke.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/work")
    ap.add_argument("--out", required=True)
    ap.add_argument("--need", type=int, default=5, help="clean clips per language")
    ap.add_argument("--budget", type=int, default=60)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(os.path.join(args.work, "manifest.all.jsonl"),
                                        encoding="utf-8")]
    dirty = [json.loads(l) for l in open(os.path.join(DIRTY_MANIFEST), encoding="utf-8")]
    for d in dirty:
        d["dirty"] = True
    used_ids = {d["id"] for d in dirty}
    print("dirty clips:", len(dirty), flush=True)

    clean = {"zh": [], "en": []}
    for lang in ["zh", "en"]:
        scanned = 0
        for r in [x for x in rows if x["lang"] == lang]:
            if len(clean[lang]) >= args.need or scanned >= args.budget:
                break
            if r["id"] in used_ids:
                continue
            scanned += 1
            try:
                raw = sf_asr(r["wav"])
            except Exception as e:  # noqa: BLE001
                print("ASR FAIL", r["id"], repr(e)[:100], flush=True)
                continue
            h = norm_zh(raw) if lang == "zh" else norm_en(raw)
            rf = norm_zh(r["ref"]) if lang == "zh" else norm_en(r["ref"])
            if not h or len(h) < 8:
                continue
            e = err_rate(list(rf) if lang == "zh" else rf.split(),
                         list(h) if lang == "zh" else h.split())
            tag = "CLEAN" if e == 0 else "     "
            print(f"{tag} {lang} scanned={scanned} {r['id']} err={e:.4f}", flush=True)
            if e == 0 and len(clean[lang]) < args.need:
                clean[lang].append({"id": r["id"], "wav": r["wav"], "lang": lang,
                                    "ref": r["ref"], "hyp_raw": raw, "hyp": h,
                                    "err_rate": 0, "bad_positions": [], "dirty": False})
            time.sleep(0.2)

    out_rows = dirty + clean["zh"] + clean["en"]
    with open(args.out, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_clean = len(clean["zh"]) + len(clean["en"])
    print(f"manifest: {args.out} rows={len(out_rows)} dirty={len(dirty)} clean={n_clean}",
          flush=True)


if __name__ == "__main__":
    main()
