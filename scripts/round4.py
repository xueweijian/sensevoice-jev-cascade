#!/usr/bin/env python3
"""Round 4: correction-technique matrix (Baoyu prompt / RLLM-CF stages /
transcript-fixer justification) vs rounds 1-3 baselines.

Conditions (each = one correction pipeline):
  B0  naive minimal prompt (rounds 1-3 control B)
  E1  Baoyu prompt (anti-deletion guard, verbatim style)
  E2  LLM self pre-detection -> fix only listed positions (RLLM-CF stage 1)
  E3  B0 + verification pass, verifier curates final text (RLLM-CF stage 3)
  E4  justification-only edits: JSON [{i,from,to,reason}], reason must be an
      ASR error type (transcript-fixer core principle)
  E5  B0 + few-shot real exemplars (ASR-EC prompting upper bound)
  E6  E1 + E3 (guard + verification)
  E7  E2 detection + E4 justification (lean RLLM-CF)
  E8  jev-1.13-free locator + E4 backfill + E3 verify (full config)
  E9  E4 on 5-line batches (granularity A/B vs E4 single)

Models: v4flash (suanli free) / d41 (4.1-flash, thinking OFF via
reasoning_effort:none) / d41think (4.1-flash, thinking on).

Safety protocol: dirty clips measure correction power; CLEAN clips measure
damage (err must stay 0) and deletion (len ratio >= 0.95).
"""
import argparse
import concurrent.futures as cf
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.parse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_ec import (norm_zh, norm_en, err_rate, changed_positions,  # noqa: E402
                    systemone, SUANLI_CHAT_URL)

OC_URL = "https://opencode.ai/zen/go/v1/chat/completions"


# ---------------------------------------------------------------- LLM layer

def llm(mode, system, user):
    """One LLM call. Returns (content, latency_s). Raises after retries."""
    if mode == "v4flash":
        url = SUANLI_CHAT_URL
        key = os.environ["SUANLI_API_KEY"]
        headers = {"Authorization": "Bearer " + key}
        body = {"model": "deepseek/deepseek-v4-flash-0731-free", "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": 1200}
    else:
        url = OC_URL
        key = os.environ["OPENCODE_API_KEY"]
        headers = {"Authorization": "Bearer " + key, "x-opencode-session": "r4"}
        body = {"model": "deepseek-v4.1-flash", "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0}
        if mode == "d41":          # thinking OFF (verified: 0 reasoning tokens)
            body["reasoning_effort"] = "none"
            body["max_tokens"] = 1500
        else:                       # d41think: default thinking on
            body["max_tokens"] = 4000
    last = None
    for k in range(3):
        t0 = time.time()
        try:
            r = requests.post(url, headers=headers, json=body, timeout=(10, 300))
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"], round(time.time() - t0, 2)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    raise last


def strip_wrap(text):
    t = text.strip()
    t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t.strip("`"))
    return t.strip().strip('"').strip()


# ---------------------------------------------------------------- prompts

B0_SYS_ZH = ("以下是一段语音识别(ASR)的中文转写，可能包含错字。请只纠正明确的错字，"
             "保持其余内容完全不变，直接输出纠正后的完整文本，不要解释。")
B0_SYS_EN = ("The following is an English ASR transcript that may contain errors. "
             "Fix only clear errors and keep everything else unchanged. Output the "
             "corrected transcript only.")
BAOYU_ZH = ("请把下面的语音转文本文稿重新整理，纠正其中错别字，去掉口癖，保持原有内容，"
            "但不要删减内容：")
BAOYU_EN = ("Please clean up the following speech-to-text transcript: fix typos, "
            "remove filler words, keep the original content, and DO NOT shorten or "
            "omit any content:")
DET_SYS_ZH = ("你是ASR错误检测器。只列出可疑位置，不要修改。输出JSON数组，元素形如 "
              '{"i": 字符下标(0基), "c": "该位置的字", "why": "简短理由"}。'
              "无错输出 []。不要输出其他文字。")
DET_SYS_EN = ("You are an ASR error detector. List suspicious word positions only, "
              'no rewriting. Output a JSON array like {"i": word_index_0based, '
              'w": "word", "why": "reason"}. Output [] if none.')
FIXAT_ZH = ("你是ASR纠错器。只允许修改下列指定位置，其余内容必须逐字保留。"
            "直接输出修改后的完整文本，不要解释。")
FIXAT_EN = ("Fix ONLY the listed positions in the transcript; keep every other "
            "character identical. Output the corrected transcript only.")
VER_SYS_ZH = ("你是ASR纠错审计员。给你原始转写和修改稿。逐项检查修改稿的改动："
              "若发现把原本正确的内容改错了、或删减了内容，请在修改稿基础上恢复；"
              "若全部改动合理，原样输出修改稿。只输出最终文本，不要解释。")
VER_SYS_EN = ("You are an ASR correction auditor. Compare the original transcript "
              "and the revised one. If any change broke originally-correct text or "
              "deleted content, restore it in the revision; if all changes are "
              "sound, output the revision as-is. Output the final text only.")
JUST_SYS_ZH = ("你是ASR纠错器。只输出JSON数组，每处修改一个元素："
               '{"i": 字符下标(0基), "from": "原字", "to": "改为的字", '
               '"reason": "ASR错误类型：同音/近音/漏字/多字/拼写"}。'
               "reason 必须解释这为什么是ASR可能犯的听写错误。无错输出[]。不要输出其他文字。")
JUST_SYS_EN = ("Fix ASR errors. Output ONLY a JSON array, one element per edit: "
               '{"i": word_index_0based, "from": "orig", "to": "fixed", '
               '"reason": "ASR error type"}. Every edit must be a plausible ASR '
               "mis-hearing. Output [] if none.")
FEWSHOT_ZH = """示例（真实ASR错误）：
转写：财政金融政策紧随其候而来 → 修正：财政金融政策紧随其后而来（候→后，同音）
转写：支持缴存职工购买首套和改善型自手住房 → 修正：支持缴存职工购买首套和改善型自住住房（手→住，近音）
转写：明天上午九点开会讨论预算 → 修正：明天上午九点开会讨论预算（无错，原样保留）
"""
FEWSHOT_EN = """Examples (real ASR errors):
transcript: After proceeding a few miles ... → fixed: After proceeding (proceedcing→proceeding, spelling)
transcript: the dews were suffered to exhale → fixed: (no error, keep as-is)
"""


def zh(clip):
    return clip["lang"] == "zh"


# ---------------------------------------------------------------- helpers

def apply_edits(text, edits, unit="char"):
    """Apply [{i,from,to}] with +-3 index tolerance. Returns (new_text, applied)."""
    units = list(text) if unit == "char" else text.split()
    applied = []
    for e in edits:
        try:
            i, frm, to = int(e["i"]), str(e.get("from", "")), str(e.get("to", ""))
        except Exception:  # noqa: BLE001
            continue
        if not to or to == frm:
            continue
        j = i
        if not (0 <= j < len(units)) or units[j] != frm:
            found = None
            for d in range(1, 4):
                if i - d >= 0 and i - d < len(units) and units[i - d] == frm:
                    found = i - d
                    break
                if i + d < len(units) and units[i + d] == frm:
                    found = i + d
                    break
            if found is None:
                continue
            j = found
        units[j] = to
        applied.append({"i": j, "from": frm, "to": to, "reason": e.get("reason", "")})
    return ("".join(units) if unit == "char" else " ".join(units)), applied


def parse_json_list(raw):
    t = strip_wrap(raw)
    m = re.search(r"\[.*\]", t, re.S)
    if m:
        try:
            out = json.loads(m.group())
            return out if isinstance(out, list) else []
        except Exception:  # noqa: BLE001
            pass
    objs = re.findall(r"\{[^{}]*\}", t)
    arr = []
    for o in objs:
        try:
            d = json.loads(o)
            if "i" in d:
                arr.append(d)
        except Exception:  # noqa: BLE001
            continue
    return arr


def norm(text, lang):
    return norm_zh(text) if lang == "zh" else norm_en(text)


# ---------------------------------------------------------------- conditions

def cond_B0(clip, mode):
    s, sysmsg = clip["hyp_raw"], (B0_SYS_ZH if zh(clip) else B0_SYS_EN)
    out, lat = llm(mode, sysmsg, s)
    return {"out": strip_wrap(out), "calls": 1, "lat": [lat], "notes": []}


def cond_E1(clip, mode):
    s, sysmsg = clip["hyp_raw"], (BAOYU_ZH if zh(clip) else BAOYU_EN)
    out, lat = llm(mode, "You are a careful transcription editor.", sysmsg + "\n" + s)
    return {"out": strip_wrap(out), "calls": 1, "lat": [lat], "notes": []}


def cond_E2(clip, mode):
    det_sys = DET_SYS_ZH if zh(clip) else DET_SYS_EN
    raw, lat1 = llm(mode, det_sys, clip["hyp_raw"])
    positions = parse_json_list(raw)
    if not positions:
        return {"out": clip["hyp_raw"], "calls": 1, "lat": [lat1],
                "notes": [f"det:{len(positions)}"]}
    fix_sys = FIXAT_ZH if zh(clip) else FIXAT_EN
    user = (f"转写：{clip['hyp_raw']}\n只允许修改的位置："
            + json.dumps(positions, ensure_ascii=False))
    out, lat2 = llm(mode, fix_sys, user)
    return {"out": strip_wrap(out), "calls": 2, "lat": [lat1, lat2],
            "notes": [f"det:{len(positions)}"]}


def cond_E3(clip, mode):
    s, sysmsg = clip["hyp_raw"], (B0_SYS_ZH if zh(clip) else B0_SYS_EN)
    fixed, lat1 = llm(mode, sysmsg, s)
    fixed = strip_wrap(fixed)
    ver_sys = VER_SYS_ZH if zh(clip) else VER_SYS_EN
    user = (json.dumps({"原始转写": clip["hyp_raw"], "修改稿": fixed},
                       ensure_ascii=False) if zh(clip) else
            json.dumps({"original": clip["hyp_raw"], "revised": fixed}))
    final, lat2 = llm(mode, ver_sys, user)
    return {"out": strip_wrap(final), "calls": 2, "lat": [lat1, lat2], "notes": []}


def cond_E4(clip, mode):
    just_sys = JUST_SYS_ZH if zh(clip) else JUST_SYS_EN
    raw, lat1 = llm(mode, just_sys, clip["hyp_raw"])
    edits = parse_json_list(raw)
    out, applied = apply_edits(clip["hyp_raw"], edits,
                               "char" if zh(clip) else "word")
    return {"out": out, "calls": 1, "lat": [lat1],
            "notes": [f"edits:{len(applied)}"]}


def cond_E5(clip, mode):
    if zh(clip):
        sysmsg = B0_SYS_ZH + "\n\n" + FEWSHOT_ZH
    else:
        sysmsg = B0_SYS_EN + "\n\n" + FEWSHOT_EN
    out, lat = llm(mode, sysmsg, clip["hyp_raw"])
    return {"out": strip_wrap(out), "calls": 1, "lat": [lat], "notes": []}


def cond_E6(clip, mode):
    s, sysmsg = clip["hyp_raw"], (BAOYU_ZH if zh(clip) else BAOYU_EN)
    fixed, lat1 = llm(mode, "You are a careful transcription editor.", sysmsg + "\n" + s)
    fixed = strip_wrap(fixed)
    ver_sys = VER_SYS_ZH if zh(clip) else VER_SYS_EN
    user = (json.dumps({"原始转写": clip["hyp_raw"], "修改稿": fixed},
                       ensure_ascii=False) if zh(clip) else
            json.dumps({"original": clip["hyp_raw"], "revised": fixed}))
    final, lat2 = llm(mode, ver_sys, user)
    return {"out": strip_wrap(final), "calls": 2, "lat": [lat1, lat2], "notes": []}


def cond_E7(clip, mode):
    det_sys = DET_SYS_ZH if zh(clip) else DET_SYS_EN
    raw, lat1 = llm(mode, det_sys, clip["hyp_raw"])
    positions = parse_json_list(raw)
    if not positions:
        return {"out": clip["hyp_raw"], "calls": 1, "lat": [lat1],
                "notes": [f"det:0"]}
    just_sys = (JUST_SYS_ZH if zh(clip) else JUST_SYS_EN) + (
        "\n只允许修改以下位置：" + json.dumps(positions, ensure_ascii=False))
    raw2, lat2 = llm(mode, just_sys, clip["hyp_raw"])
    edits = parse_json_list(raw2)
    out, applied = apply_edits(clip["hyp_raw"], edits,
                               "char" if zh(clip) else "word")
    return {"out": out, "calls": 2, "lat": [lat1, lat2],
            "notes": [f"det:{len(positions)}", f"edits:{len(applied)}"]}


def _same_sound(ch, py_index, cap=24):
    try:
        from pypinyin import lazy_pinyin
        py = lazy_pinyin(ch)[0]
    except Exception:  # noqa: BLE001
        return []
    return [c for c in py_index.get(py, []) if c != ch][:cap]


def cond_E8(clip, mode, py_index=None):
    """jev locator (opencode systemone) + justification backfill + verify.
    Operates in NORMALIZED domain (same as rounds 1-3 cascade)."""
    hyp_n = norm(clip["hyp_raw"], clip["lang"])
    ref_n = norm(clip["ref"], clip["lang"])
    units = list(hyp_n) if zh(clip) else hyp_n.split()
    lat = []
    questions = {"has_error": {"type": "noul",
                               "instructions": "转写文本中存在用错/写错的字词（如同音字误用、漏字）",
                               "criteria": {"true": "存在错字或漏字", "false": "全部正确"}}}
    for i, u in enumerate(units[:40]):
        label = "字" if zh(clip) else "词"
        questions[f"u{i}"] = {"type": "noul",
                              "instructions": f"第{i}个{label}「{u}」（下标{i}，从0数起）在此句中用法正确"}
    state = json.dumps({"语言": "中文普通话" if zh(clip) else "English",
                        "ASR转写": hyp_n,
                        "逐字列表_下标即位置" if zh(clip) else "words_by_index": units},
                       ensure_ascii=False)
    t0 = time.time()
    answers = systemone("jev-1.13-free", state, questions, "opencode")
    lat.append(round(time.time() - t0, 2))
    he = (answers.get("has_error") or {}).get("noul")
    chosen = []
    if isinstance(he, (int, float)) and he >= 0.35:
        sus = []
        for i in range(min(len(units), 40)):
            a = answers.get(f"u{i}")
            if isinstance(a, dict) and isinstance(a.get("noul"), (int, float)):
                sus.append((1.0 - float(a["noul"]), i))
        chosen = [i for p, i in sorted(sus, reverse=True) if p >= 0.5]
        if not chosen and sus and he >= 0.7:
            chosen = [max(sus)[1]]
    text = hyp_n
    if chosen:
        if zh(clip) and py_index:
            items = [{"i": i, "当前字": units[i],
                      "同音候选": _same_sound(units[i], py_index)} for i in chosen]
            sysmsg = (JUST_SYS_ZH + "\n只允许修改以下位置：" +
                      json.dumps(items, ensure_ascii=False))
        else:
            sysmsg = (JUST_SYS_EN + "\nOnly fix these positions: " +
                      json.dumps([{"i": i, "w": units[i]} for i in chosen]))
        raw, l2 = llm(mode, sysmsg, hyp_n)
        lat.append(l2)
        edits = parse_json_list(raw)
        text, applied = apply_edits(hyp_n, edits, "char" if zh(clip) else "word")
    # verify pass
    ver_sys = VER_SYS_ZH if zh(clip) else VER_SYS_EN
    user = (json.dumps({"原始转写": hyp_n, "修改稿": text}, ensure_ascii=False)
            if zh(clip) else json.dumps({"original": hyp_n, "revised": text}))
    final, l3 = llm(mode, ver_sys, user)
    lat.append(l3)
    return {"out": strip_wrap(final), "calls": 1 + (1 if chosen else 0) + 1,
            "lat": lat, "notes": [f"jev_det:{len(chosen)}"],
            "normalized_domain": True}


CONDS = {"B0": cond_B0, "E1": cond_E1, "E2": cond_E2, "E3": cond_E3, "E4": cond_E4,
         "E5": cond_E5, "E6": cond_E6, "E7": cond_E7}


# ---------------------------------------------------------------- E9 batch

def run_E9(clips, mode, repeats):
    """E4 justification applied to 5-line batches instead of single lines."""
    records = []
    groups = {}
    for c in clips:
        groups.setdefault((c["lang"], c.get("dirty", True)), []).append(c)
    for (lang, dirty), members in sorted(groups.items()):
        for rep in range(1, repeats + 1):
            batch = members[:5]
            if not batch:
                continue
            just_sys = (JUST_SYS_ZH if lang == "zh" else JUST_SYS_EN).replace(
                "字符下标(0基)", "行内字符下标(0基)").replace(
                "word_index_0based", "line,word_index_0based")
            lines = "\n".join(f"L{k}: {c['hyp_raw']}" for k, c in enumerate(batch))
            user = ("以下5行是独立的语音转写。逐行检查，输出JSON数组，每处修改一个元素："
                    '{"line": 行号, "i": 行内下标, "from": "原字", "to": "改", '
                    '"reason": "ASR错误类型"}。无错输出[]。\n' + lines) if lang == "zh" else (
                "Below are 5 independent ASR transcript lines. Output ONLY a JSON "
                'array of edits: {"line": k, "i": in-line index, "from": "orig", '
                '"to": "fixed", "reason": "..."}. Output [] if none.\n' + lines)
            t0 = time.time()
            try:
                raw, l1 = llm(mode, just_sys, user)
                edits = parse_json_list(raw)
                per_line = {}
                for e in edits:
                    per_line.setdefault(int(e.get("line", -1)), []).append(e)
                for k, c in enumerate(batch):
                    line_edits = per_line.get(k, [])
                    out, applied = apply_edits(c["hyp_raw"], line_edits,
                                               "char" if lang == "zh" else "word")
                    records.append(_record(c, out, 1, [l1],
                                           [f"edits:{len(applied)}"], rep, time.time() - t0))
            except Exception as ex:  # noqa: BLE001
                for c in batch:
                    records.append({"id": c["id"], "repeat": rep, "error": repr(ex)[:200],
                                    "lang": lang, "dirty": c.get("dirty", True),
                                    "err_before": None, "err_after": None})
    return records


# ---------------------------------------------------------------- runner

def _record(clip, out_text, calls, lats, notes, rep, wall):
    lang = clip["lang"]
    in_n = norm(clip["hyp_raw"], lang)
    out_n = norm(out_text, lang)
    ref_n = norm(clip["ref"], lang)
    i_seq = list(in_n) if lang == "zh" else in_n.split()
    o_seq = list(out_n) if lang == "zh" else out_n.split()
    r_seq = list(ref_n) if lang == "zh" else ref_n.split()
    dirty = clip.get("dirty", True)
    rec = {"id": clip["id"], "lang": lang, "dirty": dirty, "repeat": rep,
           "err_before": round(err_rate(r_seq, i_seq), 4),
           "err_after": round(err_rate(r_seq, o_seq), 4),
           "changed": changed_positions(i_seq, o_seq),
           "len_ratio": round(len(o_seq) / len(i_seq), 3) if i_seq else 1.0,
           "calls": calls, "lat": lats, "wall": round(wall, 2),
           "notes": notes, "out": out_n}
    return rec


def run_condition(condition, model, clips, repeats, concurrency, py_index):
    records = []
    if condition == "E9":
        return run_E9(clips, model, repeats)

    def work(item):
        clip, rep = item
        t0 = time.time()
        try:
            if condition == "E8":
                r = cond_E8(clip, model, py_index)
            else:
                r = CONDS[condition](clip, model)
            return _record(clip, r["out"], r["calls"], r["lat"], r["notes"],
                           rep, time.time() - t0)
        except Exception as ex:  # noqa: BLE001
            return {"id": clip["id"], "lang": clip["lang"],
                    "dirty": clip.get("dirty", True), "repeat": rep,
                    "error": repr(ex)[:200], "err_before": None, "err_after": None}

    items = [(c, rep) for rep in range(1, repeats + 1) for c in clips]
    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        records = list(ex.map(work, items))
    return records


def summarize(records):
    ok = [r for r in records if r.get("err_after") is not None]
    errs = [r for r in records if r.get("error")]
    dirty = [r for r in ok if r["dirty"]]
    clean = [r for r in ok if not r["dirty"]]
    lat = [l for r in ok for l in (r.get("lat") or [])]

    def m(xs):
        return round(statistics.mean(xs), 4) if xs else None

    lats_sorted = sorted(lat)
    return {
        "n_ok": len(ok), "n_err": len(errs),
        "dirty_n": len(dirty),
        "dirty_err_before": m([r["err_before"] for r in dirty]),
        "dirty_err_after": m([r["err_after"] for r in dirty]),
        "dirty_improved": sum(1 for r in dirty if r["err_after"] < r["err_before"]),
        "dirty_worsened": sum(1 for r in dirty if r["err_after"] > r["err_before"]),
        "clean_n": len(clean),
        "clean_damaged": sum(1 for r in clean if r["err_after"] > 0),
        "clean_changed_chars": sum(len(r.get("changed") or []) for r in clean),
        "min_len_ratio": min([r["len_ratio"] for r in ok], default=None),
        "calls_mean": m([r.get("calls", 0) for r in ok]),
        "lat_p50": lats_sorted[len(lats_sorted) // 2] if lats_sorted else None,
        "lat_p99": lats_sorted[int(len(lats_sorted) * 0.99) - 1] if lats_sorted else None,
        "safe": (len(clean) > 0 and all(r["err_after"] == 0 for r in clean)
                 and all((r.get("len_ratio") or 1) >= 0.75 for r in ok)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", required=True)
    ap.add_argument("--model", required=True, choices=["v4flash", "d41", "d41think"])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--pinyin-index", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()

    random.seed(42)
    time.sleep(random.uniform(0, 20))  # stagger matrix start (rate-limit guard)

    py_index = {}
    if args.pinyin_index and os.path.exists(args.pinyin_index):
        py_index = json.load(open(args.pinyin_index, encoding="utf-8"))
    clips = [json.loads(l) for l in open(args.manifest, encoding="utf-8")]
    print(f"cond={args.condition} model={args.model} clips={len(clips)} "
          f"repeats={args.repeats}", flush=True)

    t0 = time.time()
    records = run_condition(args.condition, args.model, clips, args.repeats,
                            args.concurrency, py_index)
    out = {"condition": args.condition, "model": args.model,
           "repeats": args.repeats, "wall_min": round((time.time() - t0) / 60, 1),
           "summary": summarize(records), "records": records}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("SUMMARY", json.dumps(out["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
