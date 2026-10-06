#!/usr/bin/env python3
"""Round 6: swap the ASR backend. Does a better ASR lower the FLOOR?

Stage 1: four free + one paid SiliconFlow ASR engines transcribe the same 10 clips
         (5 zh AISHELL-1 + 5 en LibriSpeech), base err rate per engine.
Stage 2: top-2 engines' transcripts -> champion correction (asr_correct,
         gate disabled to keep the ASR comparison clean, 2 repeats).

Also catalogs engine capabilities (timestamps / speaker / duration).

Cost note: Qwen/Qwen3-ASR-1.7B is paid (¥0.000220/audio second); do not rerun
this workflow unless paid usage is explicitly approved. The other four are free.
"""
import argparse
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

import requests  # noqa: E402

from asr_ec import norm_zh, norm_en, err_rate  # noqa: E402

SF_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"

ENGINES = {
    "sensevoice": "FunAudioLLM/SenseVoiceSmall",
    "qwen3asr": "Qwen/Qwen3-ASR-1.7B",
    "xingchen-v32": "XingChenAGI/XingChenASR-V3.2",
    "xingchen-ultra": "XingChenAGI/XingChenASR-V3.2-Ultra",
    "xingchen-diarize": "XingChenAGI/XingChenASR-Diarize-V3.0",
}


def transcribe(wav, model):
    key = os.environ["SILICONFLOW_API_KEY"]
    def call():
        with open(wav, "rb") as f:
            r = requests.post(
                SF_URL,
                headers={"Authorization": "Bearer " + key},
                files={"file": (os.path.basename(wav), f)},
                data={"model": model},
                timeout=(10, 300))
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
        return r.json()
    last = None
    for k in range(3):
        try:
            return call()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    raise last


_t2s = None


def to_simplified(text):
    global _t2s
    if not text:
        return text
    if not _t2s:
        from opencc import OpenCC
        _t2s = OpenCC("t2s")
    return _t2s.convert(text)


def norm(text, lang):
    text = to_simplified(str(text))
    return norm_zh(text) if lang == "zh" else norm_en(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()

    clips = [json.loads(l) for l in open(args.manifest, encoding="utf-8")]
    clips = [c for c in clips if c.get("dirty")]  # stage 1 needs error clips
    print("dirty clips:", len(clips), flush=True)

    # ---------------- stage 1: base ASR per engine ----------------
    stage1 = {}
    for eng, model in ENGINES.items():
        t0 = time.time()
        recs = []
        for c in clips:
            try:
                raw = transcribe(c["wav"], model)
                text = raw.get("text", "")
                h = norm(text, c["lang"])
                r = norm(c["ref"], c["lang"])
                i_seq = list(h) if c["lang"] == "zh" else h.split()
                r_seq = list(r) if c["lang"] == "zh" else r.split()
                e = err_rate(r_seq, i_seq) if i_seq else (1.0 if r_seq else 0.0)
                recs.append({"id": c["id"], "lang": c["lang"], "text": text,
                             "err": round(e, 4),
                             "n_seg": len(raw.get("segments") or []),
                             "speakers": sorted({s.get("speaker") for s in
                                                 (raw.get("segments") or [])
                                                 if s.get("speaker")}),
                             "has_duration": "duration" in raw})
            except Exception as ex:  # noqa: BLE001
                recs.append({"id": c["id"], "lang": c["lang"], "error": repr(ex)[:200]})
        ok = [x for x in recs if "err" in x]
        for lang in ["zh", "en"]:
            sub = [x for x in ok if x["lang"] == lang]
            if sub:
                print(f"  {eng} {lang}: base err={statistics.mean(x['err'] for x in sub):.4f} "
                      f"n={len(sub)}", flush=True)
        stage1[eng] = {"mean_err": round(statistics.mean([x["err"] for x in ok]), 4) if ok else None,
                       "n_err": len(recs) - len(ok), "wall_s": round(time.time() - t0, 1),
                       "records": recs}
        print(f"[stage1] {eng}: mean={stage1[eng]['mean_err']} fails={stage1[eng]['n_err']} "
              f"({stage1[eng]['wall_s']}s)", flush=True)

    ranked = sorted((e for e in stage1 if stage1[e]["mean_err"] is not None),
                    key=lambda e: stage1[e]["mean_err"])
    print("ranking:", ranked, flush=True)
    top2 = ranked[:2]

    # ---------------- stage 2: champion correction on top-2 ----------------
    from asr_correct.config import Config
    from asr_correct.correct import correct_sentence
    cfg = Config(verify_enabled=True, gate_enabled=False)  # no proxy: no torch in CI
    stage2 = {}
    for eng in top2:
        model = ENGINES[eng]
        recs = []
        for c in clips:
            eng_rec = next((r for r in stage1[eng]["records"]
                            if r["id"] == c["id"] and "text" in r), None)
            if not eng_rec:
                continue
            for rep in range(1, args.repeats + 1):
                try:
                    r = correct_sentence(eng_rec["text"], cfg, log=lambda *_: None)
                    out_n = norm(r["final"], c["lang"])
                    ref_n = norm(c["ref"], c["lang"])
                    i_seq = list(norm(eng_rec["text"], c["lang"])) if c["lang"] == "zh" \
                        else norm(eng_rec["text"], c["lang"]).split()
                    o_seq = list(out_n) if c["lang"] == "zh" else out_n.split()
                    r_seq = list(ref_n) if c["lang"] == "zh" else ref_n.split()
                    recs.append({"id": c["id"], "lang": c["lang"], "repeat": rep,
                                 "err_before": round(err_rate(r_seq, i_seq), 4),
                                 "err_after": round(err_rate(r_seq, o_seq), 4),
                                 "calls": r.get("calls", 0)})
                except Exception as ex:  # noqa: BLE001
                    recs.append({"id": c["id"], "lang": c["lang"], "repeat": rep,
                                 "error": repr(ex)[:200]})
        ok = [x for x in recs if "err_after" in x]
        stage2[eng] = {
            "err_before": round(statistics.mean([x["err_before"] for x in ok]), 4) if ok else None,
            "err_after": round(statistics.mean([x["err_after"] for x in ok]), 4) if ok else None,
            "records": recs}
        print(f"[stage2] {eng}: {stage2[eng]['err_before']} -> {stage2[eng]['err_after']}",
              flush=True)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "round6.json"), "w", encoding="utf-8") as f:
        json.dump({"stage1": stage1, "stage2": stage2, "top2": top2}, f,
                  ensure_ascii=False, indent=1)

    lines = ["# Round 6：换 ASR 底座", "",
             "| 引擎（均为硅基流动） | 脏句基础错误率(zh/en) | 时间戳 | 说话人 |",
             "|---|---|---|---|"]
    for eng in ENGINES:
        s = stage1[eng]
        zh = [x["err"] for x in s["records"] if x["lang"] == "zh" and "err" in x]
        en = [x["err"] for x in s["records"] if x["lang"] == "en" and "err" in x]
        seg = any(x.get("n_seg") for x in s["records"])
        spk = any(x.get("speakers") for x in s["records"])
        zhs = f"{statistics.mean(zh):.4f}" if zh else "FAIL"
        ens = f"{statistics.mean(en):.4f}" if en else "FAIL/不支持en"
        lines.append(f"| {eng} | zh {zhs} / en {ens} | {'✅' if seg else '❌'} "
                     f"| {'✅' if spk else '❌'} |")
    lines += ["", "## 底座×纠错（前两名过冠军管线）", ""]
    for eng in top2:
        s = stage2[eng]
        lines.append(f"- **{eng}**: {s['err_before']} → {s['err_after']}")
    lines += ["", "参考：SenseVoice 底座 + 冠军管线的 R5 终值 = 0.0331。"]
    md = "\n".join(lines)
    with open(os.path.join(args.out, "round6-summary.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)


if __name__ == "__main__":
    main()
