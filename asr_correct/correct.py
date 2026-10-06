"""Correction engine: two-pass (correct -> verify) + guardrails.

Round-4-proven design:
  - pass 1 "correct": minimal-prompt full-sentence rewrite (B0 wording)
  - pass 2 "verify":  verifier curates the revision, restores over-edits
  - guards: empty-output retry, length-ratio window, edit budget
  - fallback: primary (4.1-flash thinking-off) -> v4-flash + few-shot
"""
import json
import os
import re
import time

import requests

from .config import Config
from .segment import _is_latin

CORRECT_ZH = ("以下是一段语音识别(ASR)的中文转写，可能包含错字。请只纠正明确的错字，"
              "保持其余内容完全不变，直接输出纠正后的完整文本，不要解释。")
CORRECT_EN = ("The following is an English ASR transcript that may contain errors. "
              "Fix only clear errors and keep everything else unchanged. "
              "Output the corrected transcript only.")
VERIFY_ZH = ("你是ASR纠错审计员。给你原始转写和修改稿。逐项检查修改稿的改动："
             "若发现把原本正确的内容改错了、或删减了内容，请在修改稿基础上恢复；"
             "若全部改动合理，原样输出修改稿。只输出最终文本，不要解释。")
VERIFY_EN = ("You are an ASR correction auditor. Compare the original transcript "
             "and the revised one. If any change broke originally-correct text or "
             "deleted content, restore it in the revision; if all changes are "
             "sound, output the revision as-is. Output the final text only.")
FEWSHOT_ZH = """
示例（真实ASR错误）：
转写：财政金融政策紧随其候而来 → 修正：财政金融政策紧随其后而来（候→后，同音）
转写：明天上午九点开会讨论预算 → 修正：明天上午九点开会讨论预算（无错，原样保留）
"""
FEWSHOT_EN = """
Example (real ASR error):
transcript: After proceeding a few miles → fixed: (proceedcing→proceeding, spelling)
transcript: no error -> keep as-is
"""


def llm_call(model_id, system, user, cfg):
    """One LLM call. Returns (content, latency_s)."""
    spec = cfg.model_spec(model_id)
    key = os.environ.get(spec["key_env"])
    if not key:
        raise RuntimeError(f"env {spec['key_env']} not set for model {model_id}")
    headers = {"Authorization": "Bearer " + key}
    if spec.get("session_header"):
        headers["x-opencode-session"] = spec["session_header"]
    body = {"model": spec["model"],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": spec.get("max_tokens", 1200)}
    if spec.get("reasoning_effort"):
        body["reasoning_effort"] = spec["reasoning_effort"]
    last = None
    for k in range(cfg.retries):
        t0 = time.time()
        try:
            r = requests.post(spec["url"], headers=headers, json=body,
                              timeout=(10, cfg.timeout))
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"] or ""
            return content, round(time.time() - t0, 2)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    raise last


def strip_wrap(text):
    t = (text or "").strip()
    t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t.strip("`"))
    return t.strip().strip('"').strip()


def edits_between(old, new):
    """Aligned edit list [(pos_in_old, from, to)] via difflib."""
    import difflib
    a = list(old)
    b = list(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    edits = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                edits.append((min(i1 + k, i2 - 1) if i2 > i1 else i1,
                              a[i1 + k] if i1 + k < i2 else "",
                              b[j1 + k] if j1 + k < j2 else ""))
        elif tag == "delete":
            for k in range(i1, i2):
                edits.append((k, a[k], ""))
        elif tag == "insert":
            edits.append((i1, "", b[j1:j2][:6]))
    return edits


def guard(original, candidate, cfg):
    """Return (ok, reason). Candidate must not be empty nor a rewrite."""
    if not candidate or not candidate.strip():
        return False, "empty"
    lo, hi = cfg.min_len_ratio, cfg.max_len_ratio
    ratio = len(candidate) / max(len(original), 1)
    if ratio < lo:
        return False, f"deletion_suspect(len_ratio={ratio:.2f})"
    if ratio > hi:
        return False, f"rewrite_suspect(len_ratio={ratio:.2f})"
    budget = max(2, int(len(original) * cfg.max_edit_ratio))
    n = len(edits_between(original, candidate))
    if n > budget * 3:  # hard stop far above budget
        return False, f"edit_budget_exceeded({n}>{budget * 3})"
    return True, ""


def correct_sentence(sentence, cfg, log=print):
    """Two-pass correction with guards and model fallback. Never raises
    for guard reasons — falls back to the original sentence."""
    lang = "en" if _is_latin(sentence) else "zh"
    correct_sys = CORRECT_ZH if lang == "zh" else CORRECT_EN
    verify_sys = VERIFY_ZH if lang == "zh" else VERIFY_EN
    res = {"orig": sentence, "final": sentence, "edits": [], "guards": [],
           "calls": 0, "models": [], "lat": [], "pass2": False}

    chain = []
    for m in (cfg.llm_primary, cfg.llm_fallback):
        if m and m not in chain and cfg.has_key(m):
            chain.append(m)
    used_primary = False
    for model_id in dict.fromkeys(chain):
        # -------- pass 1: correct --------
        system = correct_sys
        spec = cfg.model_spec(model_id)
        if spec.get("fewshot"):
            system += FEWSHOT_ZH if lang == "zh" else FEWSHOT_EN
        user = sentence
        fixed, lat = "", None
        for attempt in range(1 + cfg.empty_retries):
            fixed, lat = llm_call(model_id, system, user, cfg)
            res["calls"] += 1
            res["lat"].append(lat)
            if fixed.strip():
                break
            user = sentence + "\n（必须输出修正后的完整文本，禁止空白输出）"
        fixed = strip_wrap(fixed)
        ok, why = guard(sentence, fixed, cfg)
        if not ok:
            res["guards"].append(f"pass1@{model_id}:{why}")
            log(f"  [guard] pass1 {model_id} rejected: {why}")
            continue
        # -------- pass 2: verify --------
        if cfg.verify_enabled:
            vmodel = cfg.llm_verify if cfg.has_key(cfg.llm_verify) else model_id
            payload = (json.dumps({"原始转写": sentence, "修改稿": fixed},
                                  ensure_ascii=False) if lang == "zh" else
                       json.dumps({"original": sentence, "revised": fixed}))
            final, vlat = llm_call(vmodel, verify_sys, payload, cfg)
            res["calls"] += 1
            res["lat"].append(vlat)
            res["pass2"] = True
            final = strip_wrap(final)
            ok2, why2 = guard(sentence, final, cfg)
            if not ok2:
                res["guards"].append(f"pass2@{vmodel}:{why2}->keep_pass1")
                log(f"  [guard] pass2 rejected ({why2}), keeping pass1")
                final = fixed
        else:
            final = fixed
        res["final"] = final
        res["edits"] = edits_between(sentence, final)
        res["models"] = [model_id] + ([cfg.llm_verify] if res["pass2"] else [])
        used_primary = model_id == cfg.llm_primary
        res["used_fallback"] = not used_primary
        return res
    # all models failed guards -> keep original (visible garble > fluent wrong)
    res["guards"].append("all_models_failed->original")
    return res
