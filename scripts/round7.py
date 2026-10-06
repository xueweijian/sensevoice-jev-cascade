#!/usr/bin/env python3
"""Round 7: every FREE SiliconFlow ASR -> champion correction.

Qwen3-ASR-1.7B is intentionally absent: it is paid and was already measured
in Round 6. This workflow only calls the four free engines:
  SenseVoiceSmall, XingChen V3.2, XingChen Ultra, XingChen Diarize.

For every engine:
  1. transcribe the same 20 clips (10 dirty + 10 source-clean)
  2. measure raw ASR error
  3. feed the transcript into the production champion:
       deepseek-v4.1-flash, reasoning_effort=none, correct -> verify,
       gate disabled so this isolates ASR backend + correction
  4. repeat correction twice; ASR is called once per audio/model.

Diarize uses segment text (without speaker labels) for fair ASR scoring, while
retaining segment/speaker metadata in the JSON report.
"""
import argparse
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import requests  # noqa: E402

from asr_ec import norm_en, norm_zh, err_rate  # noqa: E402

SF_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"

# Deliberately free-only. Do not add Qwen here without explicit paid approval.
FREE_ENGINES = {
    "sensevoice": "FunAudioLLM/SenseVoiceSmall",
    "xingchen-v32": "XingChenAGI/XingChenASR-V3.2",
    "xingchen-ultra": "XingChenAGI/XingChenASR-V3.2-Ultra",
    "xingchen-diarize": "XingChenAGI/XingChenASR-Diarize-V3.0",
}


def _request(wav, model):
    key = os.environ["SILICONFLOW_API_KEY"]
    with open(wav, "rb") as f:
        r = requests.post(
            SF_URL,
            headers={"Authorization": "Bearer " + key},
            files={"file": (os.path.basename(wav), f)},
            data={"model": model},
            timeout=(10, 300),
        )
    if r.status_code != 200:
        raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:250]}")
    return r.json()


def transcribe(wav, model):
    last = None
    for attempt in range(3):
        try:
            return _request(wav, model)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def eval_text(body, engine):
    """Return text for ASR scoring, plus metadata."""
    segments = body.get("segments") or []
    if engine == "xingchen-diarize" and segments:
        # Top-level diarize text contains "1: ..." labels. Do not score those
        # labels as transcription errors; retain them separately as metadata.
        text = " ".join(str(s.get("text", "")).strip() for s in segments).strip()
    else:
        text = str(body.get("text", ""))
    speakers = sorted({str(s.get("speaker")) for s in segments if s.get("speaker") is not None})
    return text, {
        "raw_text": body.get("text", ""),
        "duration": body.get("duration"),
        "segments": segments,
        "speakers": speakers,
        "has_timestamps": bool(segments and all("start" in s and "end" in s for s in segments)),
    }


def norm(text, lang):
    return norm_zh(text) if lang == "zh" else norm_en(text)


def seq(text, lang):
    n = norm(text, lang)
    return list(n) if lang == "zh" else n.split()


def base_record(clip, engine, body):
    text, meta = eval_text(body, engine)
    hyp = seq(text, clip["lang"])
    ref = seq(clip["ref"], clip["lang"])
    return {
        "id": clip["id"],
        "engine": engine,
        "lang": clip["lang"],
        "source_clean": not clip.get("dirty", True),
        "text": text,
        "raw_text": meta.pop("raw_text"),
        "meta": meta,
        "err_raw": round(err_rate(ref, hyp), 4) if hyp else 1.0,
    }


def correction_record(base, clip, cfg, repeat):
    from asr_correct.correct import correct_sentence

    t0 = time.time()
    try:
        r = correct_sentence(base["text"], cfg, log=lambda *_: None)
        out = r["final"]
        ref = seq(clip["ref"], clip["lang"])
        out_seq = seq(out, clip["lang"])
        return {
            "id": base["id"],
            "engine": base["engine"],
            "lang": base["lang"],
            "source_clean": base["source_clean"],
            "repeat": repeat,
            "err_raw": base["err_raw"],
            "err_after": round(err_rate(ref, out_seq), 4),
            "output": norm(out, clip["lang"]),
            "calls": r.get("calls", 0),
            "lat": r.get("lat", []),
            "wall_s": round(time.time() - t0, 2),
            "guards": r.get("guards", []),
            "edits": r.get("edits", []),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "id": base["id"], "engine": base["engine"], "lang": base["lang"],
            "source_clean": base["source_clean"], "repeat": repeat,
            "err_raw": base["err_raw"], "error": repr(e)[:300],
        }


def mean(xs):
    return round(statistics.mean(xs), 4) if xs else None


def group_summary(records):
    ok = [r for r in records if "err_after" in r]
    dirty = [r for r in ok if not r["source_clean"]]
    clean = [r for r in ok if r["source_clean"]]

    def one(rs):
        if not rs:
            return {"n": 0}
        raw = mean([r["err_raw"] for r in rs])
        after = mean([r["err_after"] for r in rs])
        return {
            "n": len(rs),
            "raw": raw,
            "after": after,
            "relative_change_pct": round((after - raw) / raw * 100, 1) if raw else 0.0,
            "improved": sum(r["err_after"] < r["err_raw"] for r in rs),
            "same": sum(r["err_after"] == r["err_raw"] for r in rs),
            "worsened": sum(r["err_after"] > r["err_raw"] for r in rs),
            "calls_mean": mean([r.get("calls", 0) for r in rs]),
            "wall_p50": sorted(r.get("wall_s", 0) for r in rs)[len(rs) // 2],
        }

    all_ok = one(ok)
    return {
        "all": all_ok,
        "dirty_source": one(dirty),
        "clean_source": one(clean),
        "errors": len(records) - len(ok),
        "clean_after_nonzero": sum(r["err_after"] > 0 for r in clean),
        "clean_worsened_vs_raw": sum(r["err_after"] > r["err_raw"] for r in clean),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()

    clips = [json.loads(line) for line in open(args.manifest, encoding="utf-8")]
    print(f"clips={len(clips)} free_engines={list(FREE_ENGINES)}", flush=True)

    stage1 = {}
    for engine, model in FREE_ENGINES.items():
        print(f"== ASR {engine}: {model}", flush=True)
        records = []
        for clip in clips:
            try:
                t0 = time.time()
                body = transcribe(clip["wav"], model)
                r = base_record(clip, engine, body)
                r["asr_wall_s"] = round(time.time() - t0, 2)
                records.append(r)
                print(f"  {clip['lang']} {clip['id'][-10:]} raw_err={r['err_raw']} "
                      f"segments={len(r['meta']['segments'])}", flush=True)
            except Exception as e:  # noqa: BLE001
                records.append({"id": clip["id"], "engine": engine,
                                "lang": clip["lang"], "source_clean": not clip.get("dirty", True),
                                "error": repr(e)[:300]})
                print(f"  FAIL {clip['id']}: {e!r}", flush=True)
        stage1[engine] = records

    # The champion correction is isolated from the CSC gate here. This answers
    # exactly: each ASR backend + same correct->verify pipeline.
    from asr_correct.config import Config
    cfg = Config(verify_enabled=True, gate_enabled=False,
                 llm_primary="d41n", llm_verify="d41n", llm_fallback="")
    stage2 = {}
    for engine, records in stage1.items():
        print(f"== CORRECT {engine} x{args.repeats}", flush=True)
        by_id = {r["id"]: r for r in records if "text" in r}
        out = []
        for clip in clips:
            base = by_id.get(clip["id"])
            if not base:
                continue
            for repeat in range(1, args.repeats + 1):
                r = correction_record(base, clip, cfg, repeat)
                out.append(r)
                print(f"  {clip['lang']} {clip['id'][-10:]} r{repeat} "
                      f"{r.get('err_raw')} -> {r.get('err_after', 'FAIL')}", flush=True)
        stage2[engine] = out

    summaries = {engine: group_summary(recs) for engine, recs in stage2.items()}
    os.makedirs(args.out, exist_ok=True)
    payload = {"free_engines": FREE_ENGINES, "stage1": stage1,
               "stage2": stage2, "summary": summaries,
               "note": "Qwen3-ASR-1.7B intentionally excluded: paid model."}
    with open(os.path.join(args.out, "round7.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    lines = ["# Round 7：全部免费 ASR × 冠军纠错", "",
             "Qwen3-ASR-1.7B 已明确收费，本轮完全不调用。所有模型使用同一 20 条考卷；"
             "每个 ASR 只调用一次/音频，之后统一接 4.1flash 关思考两遍流，CSC 门控关闭。", "",
             "## 总体：原始 ASR → 冠军纠错后", "",
             "| 免费 ASR | 原始错误率 | 纠错后 | 变化（负数=变好） | 改善/持平/恶化 |", 
             "|---|---:|---:|---:|---:|"]
    for engine in FREE_ENGINES:
        s = summaries[engine]["all"]
        lines.append(f"| {engine} | {s.get('raw')} | {s.get('after')} "
                     f"| {s.get('relative_change_pct')}% | "
                     f"{s.get('improved')}/{s.get('same')}/{s.get('worsened')} |")
    lines += ["", "## 按来源分组", "",
              "`source_dirty` = 原 SenseVoice 筛出的 10 条脏音频；`source_clean` = 原 SenseVoice 筛出的 10 条净音频。"
              "换 ASR 后，净音频不保证对新 ASR 仍然完全正确，所以同时报告原始错误率。", "",
              "| ASR | 组 | 原始 | 纠错后 | 变化 | 改善/持平/恶化 | 纠错后非零句 |", 
              "|---|---|---:|---:|---:|---:|---:|"]
    for engine in FREE_ENGINES:
        for label, key in [("dirty", "dirty_source"), ("clean", "clean_source")]:
            s = summaries[engine][key]
            lines.append(f"| {engine} | {label} | {s.get('raw')} | {s.get('after')} "
                         f"| {s.get('relative_change_pct')}% "
                         f"| {s.get('improved')}/{s.get('same')}/{s.get('worsened')} "
                         f"| {s.get('n') if label=='clean' else '-'} |")
    lines += ["", "## 时间戳/说话人", "",
              "Diarize 的纠错输入使用 segments.text 去掉 speaker 标签；原始 segments 和 speakers 仍保存在 round7.json。"]
    for engine in FREE_ENGINES:
        recs = stage1[engine]
        has_ts = any(r.get("meta", {}).get("has_timestamps") for r in recs)
        speakers = sorted({sp for r in recs for sp in r.get("meta", {}).get("speakers", [])})
        lines.append(f"- {engine}: timestamps={'yes' if has_ts else 'no'}, speakers={speakers or 'none'}")
    with open(os.path.join(args.out, "round7-summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
