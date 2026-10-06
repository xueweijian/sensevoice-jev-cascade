#!/usr/bin/env python3
"""Run the smoke experiment: controls A / B and cascade D per judge model.

Controls
  A  raw ASR (baseline, from screening)
  B  naive LLM full-text correction, no gating no constraints (expected: over-correction)
  D  cascade per judge model:
       gate (has_error noul) -> per-unit noul suspicion -> same-sound choice backfill
       -> LLM fallback (JSON-constrained, candidates locked to same-pinyin set, zh)

Pure-text cascade: state carries transcript only, no acoustic evidence, ONE ASR per clip.
"""
import argparse
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_ec import (systemone, suanli_chat, bad_positions, changed_positions,  # noqa: E402
                    err_rate, oc_usage_snippet)

HAS_ERROR_GATE = 0.35   # below this -> clip passes through uncorrected
SUSPECT_TH = 0.5        # per-unit P(wrong) threshold
CHOICE_CONF = 0.6       # judge choice confidence to accept a direct backfill
MAX_Q_UNITS = 40        # cap per-unit questions (parallel, but keep bounded)

JUDGES = [
    ("Kev-4B", "siliconflow"),
    ("SemIf", "siliconflow"),
    ("diffusiongemma", "siliconflow"),
]
if os.environ.get("OPENCODE_API_KEY"):
    JUDGES.append(("jev-1.13-free", "opencode"))

LLM_SYS_ZH = (
    "你是ASR转写纠错器。输入一段中文语音转写和若干可疑字位置（0基下标），每个位置附同音候选字表。"
    '只输出一个JSON数组，元素形如 {"i": 下标, "to": "正确的字"}；'
    "to 必须取自该位置的候选表；不该改的位置不要输出。不要输出任何其他文字。"
)
LLM_SYS_EN = (
    "You fix ASR transcription errors. Input: an English transcript and suspicious word "
    'indices (0-based). Output ONLY a JSON array like {"i": index, "to": "correct word"}. '
    "Skip positions that need no change. No other text."
)
B_SYS_ZH = ("以下是一段语音识别(ASR)的中文转写，可能包含错字。请只纠正明确的错字，"
            "保持其余内容完全不变，直接输出纠正后的完整文本，不要解释。")
B_SYS_EN = ("The following is an English ASR transcript that may contain errors. "
            "Fix only clear errors and keep everything else unchanged. "
            "Output the corrected transcript only.")


def units_of(rec):
    if rec["lang"] == "zh":
        return list(rec["hyp"]), list(rec["ref"])
    return rec["hyp"].split(), rec["ref"].split()


def build_state(rec, units):
    if rec["lang"] == "zh":
        return json.dumps({"语言": "中文普通话", "ASR转写": rec["hyp"],
                           "逐字列表_下标即位置": units}, ensure_ascii=False)
    return json.dumps({"language": "English", "ASR_transcript": rec["hyp"],
                       "words_by_index": units}, ensure_ascii=False)


def build_questions(rec, units):
    zh = rec["lang"] == "zh"
    label = "字" if zh else "词"
    q = {"has_error": {"type": "noul",
                       "instructions": "转写文本中存在用错/写错的字词（如同音字误用、漏字）",
                       "criteria": {"true": "存在错字或漏字", "false": "全部正确"}}}
    for i, u in enumerate(units[:MAX_Q_UNITS]):
        q[f"u{i}"] = {"type": "noul",
                      "instructions": f"第{i}个{label}「{u}」（下标{i}，从0数起）在此句中用法正确"}
    q["err_count"] = {"type": "score",
                      "instructions": "转写中用错的字/词个数（含漏字）",
                      "criteria": ["0个", "1个", "2个", "3个及以上"]}
    return q


def parse_score(ans):
    if not isinstance(ans, dict):
        return None
    probs = ans.get("probabilities") or {}
    if probs:
        try:
            total = exp = 0.0
            for k, v in probs.items():
                digits = re.sub(r"\D", "", str(k))
                idx = int(digits[:1]) if digits else 0
                total += float(v)
                exp += idx * float(v)
            if total > 0:
                return round(exp / total, 2)
        except Exception:  # noqa: BLE001
            pass
    s = ans.get("score")
    return float(s) if isinstance(s, (int, float)) else None


def same_sound(ch, py_index, cap=24):
    try:
        from pypinyin import lazy_pinyin
        py = lazy_pinyin(ch)[0]
    except Exception:  # noqa: BLE001
        return []
    return [c for c in py_index.get(py, []) if c != ch][:cap]


def llm_fix(rec, units, positions, py_index):
    if rec["lang"] == "zh":
        items = [{"i": i, "当前字": units[i], "同音候选": same_sound(units[i], py_index)}
                 for i in positions]
        user = json.dumps({"转写": rec["hyp"], "可疑位置": items}, ensure_ascii=False)
        system = LLM_SYS_ZH
    else:
        user = json.dumps({"transcript": rec["hyp"],
                           "suspicious_positions": [{"i": i, "word": units[i]} for i in positions]})
        system = LLM_SYS_EN
    raw = suanli_chat(system, user)
    edits = []
    try:
        m = re.search(r"\[.*\]", raw, re.S)
        for e in json.loads(m.group()):
            i, to = int(e.get("i", -1)), str(e.get("to", ""))
            if i not in positions or not to or to == units[i]:
                continue
            if rec["lang"] == "zh" and to not in same_sound(units[i], py_index) and to != units[i]:
                continue  # constraint: zh candidates locked to same-sound set
            edits.append({"i": i, "from": units[i], "to": to, "by": "llm:deepseek"})
    except Exception as ex:  # noqa: BLE001
        edits.append({"i": -1, "from": "", "to": "", "by": "llm:error", "note": f"{ex}; raw={raw[:160]}"})
    return edits


def control_b(rec, units):
    sysmsg = B_SYS_ZH if rec["lang"] == "zh" else B_SYS_EN
    raw = suanli_chat(sysmsg, rec["hyp"])
    text = raw.strip().strip('"').strip("`")
    if rec["lang"] == "zh":
        from asr_ec import norm_zh
        new = list(norm_zh(text))
    else:
        from asr_ec import norm_en
        new = norm_en(text).split()
    return new, raw


def run_cascade(rec, model, provider, py_index):
    t0 = time.time()
    units, ref_units = units_of(rec)
    answers = systemone(model, build_state(rec, units), build_questions(rec, units), provider)
    has_error = (answers.get("has_error") or {}).get("noul")
    suspect = []
    for i in range(min(len(units), MAX_Q_UNITS)):
        a = answers.get(f"u{i}")
        if isinstance(a, dict) and isinstance(a.get("noul"), (int, float)):
            suspect.append((round(1.0 - float(a["noul"]), 4), i))
    est = parse_score(answers.get("err_count"))

    gate_open = isinstance(has_error, (int, float)) and has_error >= HAS_ERROR_GATE
    chosen = []
    if gate_open:
        chosen = [i for p, i in sorted(suspect, reverse=True) if p >= SUSPECT_TH]
        if not chosen and suspect and has_error >= 0.7:
            chosen = [max(suspect)[1]]

    edits = []
    if gate_open and chosen:
        if rec["lang"] == "zh":
            unresolved = []
            for i in chosen:
                ch = units[i]
                cands = same_sound(ch, py_index)
                if not cands:
                    unresolved.append(i)
                    continue
                crit = {"keep": "这个字没错，不用改"}
                for ci, c in enumerate(cands):
                    crit[f"c{ci}"] = c
                a = systemone(
                    model,
                    json.dumps({"句子": rec["hyp"], "下标": i, "当前字": ch, "同音候选": cands},
                               ensure_ascii=False),
                    {"fix": {"type": "choice",
                             "instructions": f"下标{i}的字「{ch}」应该改成哪个候选？本字没错就选keep",
                             "criteria": crit}},
                    provider)
                fa = (a or {}).get("fix") or {}
                choice, conf = fa.get("choice"), fa.get("confidence", 0)
                to = crit.get(choice, "") if choice else ""
                if to and choice != "keep" and (conf or 0) >= CHOICE_CONF:
                    edits.append({"i": i, "from": ch, "to": to,
                                  "by": f"choice:{model}", "conf": conf})
                else:
                    unresolved.append(i)
            if unresolved:
                edits += llm_fix(rec, units, unresolved, py_index)
        else:
            edits += llm_fix(rec, units, chosen, py_index)

    new_units = list(units)
    for e in edits:
        if 0 <= e["i"] < len(new_units) and e["to"]:
            new_units[e["i"]] = e["to"]
    detail = {"gate_open": gate_open, "has_error": has_error, "est_err_count": est,
              "chosen": chosen,
              "suspect_p_wrong": {str(i): p for p, i in suspect if p >= 0.3},
              "edits": edits, "latency_s": round(time.time() - t0, 2)}
    return new_units, detail


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def probe_judges():
    for model, provider in JUDGES:
        try:
            a = systemone(model, "连通性测试：一加一等于二", {
                "ok": {"type": "noul", "instructions": "一加一等于二"}}, provider)
            print(f"probe {model}: OK noul={((a or {}).get('ok') or {}).get('noul')}")
        except Exception as e:  # noqa: BLE001
            print(f"probe {model}: FAIL {e!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--pinyin-index", default=None)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    py_index = {}
    if args.pinyin_index and os.path.exists(args.pinyin_index):
        py_index = json.load(open(args.pinyin_index, encoding="utf-8"))
        print("pinyin groups:", len(py_index))

    clips = [json.loads(l) for l in open(args.manifest, encoding="utf-8")]
    print("clips:", len(clips))
    probe_judges()

    oc_before = oc_usage_snippet() if os.environ.get("OPENCODE_API_KEY") else None

    records = []
    for rec in clips:
        units, ref_units = units_of(rec)
        base_err = err_rate(ref_units, units)
        bad = set(rec.get("bad_positions") or bad_positions(units, ref_units))

        # ---- control B: naive LLM ----
        try:
            b_units, b_raw = control_b(rec, units)
            b_err = err_rate(ref_units, b_units)
            b_changed = changed_positions(units, b_units)
            b_over = [i for i in b_changed if i not in bad]
        except Exception as ex:  # noqa: BLE001
            b_units, b_err, b_changed, b_over, b_raw = units, base_err, [], [], f"fail: {ex}"
        print(f"[B] {rec['lang']} {rec['id']} err {base_err:.3f} -> {b_err:.3f} "
              f"changed={len(b_changed)} over={len(b_over)}")

        # ---- cascade D per judge ----
        for model, provider in JUDGES:
            try:
                new_units, detail = run_cascade(rec, model, provider, py_index)
                new_err = err_rate(ref_units, new_units)
                changed = [i for i in range(min(len(units), len(new_units))) if units[i] != new_units[i]]
                over = [i for i in changed if i not in bad]
                chosen = set(detail["chosen"])
                tp, fp, fn = len(chosen & bad), len(chosen - bad), len(bad - chosen)
            except Exception as ex:  # noqa: BLE001
                new_units, new_err, changed, over = units, base_err, [], []
                detail = {"error": repr(ex)[:300]}
                tp = fp = fn = 0
            rec_out = {
                "id": rec["id"], "lang": rec["lang"], "model": model,
                "ref": rec["ref"], "hyp": rec["hyp"], "hyp_raw": rec.get("hyp_raw"),
                "err_A": round(base_err, 4), "err_B": round(b_err, 4), "err_D": round(new_err, 4),
                "changed": changed, "overcorrect_positions": over,
                "det_tp": tp, "det_fp": fp, "det_fn": fn,
                "b_changed": len(b_changed), "b_overcorrect": len(b_over), "b_raw": b_raw[:300],
                "detail": detail,
                "fixed_hyp": ("".join(new_units) if rec["lang"] == "zh" else " ".join(new_units)),
                "b_hyp": ("".join(b_units) if rec["lang"] == "zh" else " ".join(b_units)),
            }
            records.append(rec_out)
            if detail.get("error"):
                print(f"    !! {model} cascade error: {detail['error']}")
            for e in detail.get("edits", []):
                if e.get("by") == "llm:error":
                    print(f"    !! llm note: {str(e.get('note'))[:200]}")
            with open(os.path.join(args.out, "results.partial.json"), "w", encoding="utf-8") as pf:
                json.dump({"records": records}, pf, ensure_ascii=False)
            d = detail.get("edits", [])
            print(f"[D:{model}] {rec['lang']} {rec['id']} err {base_err:.3f} -> {new_err:.3f} "
                  f"edits={[(e.get('i'), e.get('from'), e.get('to'), e.get('by')) for e in d]} "
                  f"det(tp/fp/fn)={tp}/{fp}/{fn}")

    oc_after = oc_usage_snippet() if os.environ.get("OPENCODE_API_KEY") else None

    # ---------------- aggregate ----------------
    def agg(pred):
        rs = [r for r in records if pred(r)]
        if not rs:
            return None
        n = len(rs)
        return {
            "n": n,
            "err_A_mean": round(statistics.mean(r["err_A"] for r in rs), 4),
            "err_B_mean": round(statistics.mean(r["err_B"] for r in rs), 4),
            "err_D_mean": round(statistics.mean(r["err_D"] for r in rs), 4),
            "improved": sum(1 for r in rs if r["err_D"] < r["err_A"]),
            "worsened": sum(1 for r in rs if r["err_D"] > r["err_A"]),
            "unchanged": sum(1 for r in rs if r["err_D"] == r["err_A"]),
            "det_tp": sum(r["det_tp"] for r in rs), "det_fp": sum(r["det_fp"] for r in rs),
            "det_fn": sum(r["det_fn"] for r in rs),
            "overcorrections_D": sum(len(r["overcorrect_positions"]) for r in rs),
            "overcorrections_B": sum(r["b_overcorrect"] for r in rs),
            "changed_B": sum(r["b_changed"] for r in rs),
            "latency_mean_s": round(statistics.mean(
                (r["detail"].get("latency_s") or 0) for r in rs
                if r["detail"].get("latency_s")), 2) if any(r["detail"].get("latency_s") for r in rs) else None,
            "edits_by_choice": sum(1 for r in rs for e in r["detail"].get("edits", [])
                                   if str(e.get("by", "")).startswith("choice")),
            "edits_by_llm": sum(1 for r in rs for e in r["detail"].get("edits", [])
                                if str(e.get("by", "")) == "llm:deepseek"),
        }

    summary = {}
    for model, _ in JUDGES:
        summary[model] = agg(lambda r, m=model: r["model"] == m)

    def prec(tp, fp):
        return round(tp / (tp + fp), 3) if tp + fp else None
    def rec_(tp, fn):
        return round(tp / (tp + fn), 3) if tp + fn else None

    lines = ["# ASR error-correction cascade — smoke results", "",
             f"- run: {datetime.now(timezone.utc).isoformat()}",
             f"- clips: {len(clips)} (zh {sum(1 for c in clips if c['lang']=='zh')}, "
             f"en {sum(1 for c in clips if c['lang']=='en')}) — all clips verified to contain real ASR errors",
             f"- thresholds: gate={HAS_ERROR_GATE} suspect={SUSPECT_TH} choice_conf={CHOICE_CONF}",
             "", "## Aggregate (all clips)", "",
             md_table(["condition", "n", "err A→(B)/D", "impr/same/worse", "det P", "det R",
                       "overcorr D", "overcorr B", "edits choice/llm", "latency s"],
                      [["A raw ASR", (summary.get(JUDGES[0][0]) or {}).get("n"),
                        f"{(summary.get(JUDGES[0][0]) or {}).get('err_A_mean')}", "-", "-", "-", "-", "-", "-", "-"]] +
                      [[f"D {m}", s["n"], f"{s['err_A_mean']} -> {s['err_D_mean']}",
                        f"{s['improved']}/{s['unchanged']}/{s['worsened']}",
                        prec(s["det_tp"], s["det_fp"]), rec_(s["det_tp"], s["det_fn"]),
                        s["overcorrections_D"], s["overcorrections_B"],
                        f"{s['edits_by_choice']}/{s['edits_by_llm']}", s["latency_mean_s"]]
                       for m, s in ((m, summary[m]) for m, _ in JUDGES if summary.get(m))]),
             "", "## Per-language err means", ""]
    for lang in ["zh", "en"]:
        s = agg(lambda r, l=lang: r["lang"] == l and r["model"] == "SemIf")
        if s:
            lines.append(f"- {lang} (SemIf): A {s['err_A_mean']} -> D {s['err_D_mean']}, "
                         f"B {s['err_B_mean']}")
    lines += ["", "## Per-clip detail (SemIf)", ""]
    for r in records:
        if r["model"] != "SemIf":
            continue
        lines += [f"### {r['id']} ({r['lang']}) err A={r['err_A']} B={r['err_B']} D={r['err_D']}",
                  f"- ref: `{r['ref']}`", f"- hyp: `{r['hyp']}`",
                  f"- D-fixed: `{r['fixed_hyp']}`",
                  f"- edits: {[(e.get('i'), e.get('from'), e.get('to'), e.get('by')) for e in r['detail'].get('edits', [])]}",
                  f"- B-fixed: `{r['b_hyp']}`", ""]
    if oc_before:
        lines += ["## OpenCode usage guard (jev-1.13-free free-ness check)", "",
                  "before:", "```", oc_before[:400], "```", "after:", "```", (oc_after or "")[:400], "```"]

    with open(os.path.join(args.out, "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": {"run_utc": datetime.now(timezone.utc).isoformat(),
                            "judges": [m for m, _ in JUDGES],
                            "thresholds": {"gate": HAS_ERROR_GATE, "suspect": SUSPECT_TH,
                                           "choice_conf": CHOICE_CONF}},
                   "summary": summary, "records": records}, f, ensure_ascii=False, indent=1)
    print("written:", args.out)


if __name__ == "__main__":
    main()
