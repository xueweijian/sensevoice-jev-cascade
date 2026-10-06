#!/usr/bin/env python3
"""Shared library: API clients, text normalization, alignment, metrics.

Design: pure-text cascade, ONE ASR call per clip, zero local models.
  - ASR:          SiliconFlow FunAudioLLM/SenseVoiceSmall  (/v1/audio/transcriptions)
  - Judge:        SiliconFlow /v1/systemone  (Jev-compatible: Kev-4B / SemIf / diffusiongemma)
                  optional real Jev via OpenCode /zen/v1/systemone (jev-1.13-free)
  - LLM fallback: suanli deepseek/deepseek-v4-flash-0731-free
"""
import json
import os
import re
import time

import requests

SF_ASR_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
SF_SYS_URL = "https://api.siliconflow.cn/v1/systemone"
OC_SYS_URL = "https://opencode.ai/zen/v1/systemone"
OC_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
SUANLI_CHAT_URL = "https://api.suanli.cn/v1/chat/completions"
SUANLI_MODEL = "deepseek/deepseek-v4-flash-0731-free"
SENSEVOICE = "FunAudioLLM/SenseVoiceSmall"


def _retry(fn, n=3, base=2.0):
    last = None
    for k in range(n):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(base * (k + 1))
    raise last


def sf_asr(wav_path):
    """One ASR call. Returns raw transcript text (tags already stripped by API)."""
    def call():
        with open(wav_path, "rb") as f:
            r = requests.post(
                SF_ASR_URL,
                headers={"Authorization": "Bearer " + os.environ["SILICONFLOW_API_KEY"]},
                files={"file": (os.path.basename(wav_path), f, "audio/wav")},
                data={"model": SENSEVOICE},
                timeout=(10, 180),
            )
        r.raise_for_status()
        return r.json()["text"]
    return _retry(call)


def systemone(model, state, questions, provider="siliconflow"):
    """Jev-compatible decision call. Returns the `answers` dict."""
    if provider == "siliconflow":
        url, key = SF_SYS_URL, os.environ["SILICONFLOW_API_KEY"]
    else:
        url, key = OC_SYS_URL, os.environ["OPENCODE_API_KEY"]

    def call():
        r = requests.post(
            url,
            headers={"Authorization": "Bearer " + key},
            json={"model": model, "state": state, "questions": questions},
            timeout=(10, 180),
        )
        if r.status_code != 200:
            raise RuntimeError(f"systemone {model} HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        if "answers" not in body:
            raise RuntimeError(f"systemone {model} no answers: {json.dumps(body, ensure_ascii=False)[:300]}")
        return body["answers"]

    return _retry(call)


def suanli_chat(system, user, max_tokens=900):
    def call():
        r = requests.post(
            SUANLI_CHAT_URL,
            headers={"Authorization": "Bearer " + os.environ["SUANLI_API_KEY"]},
            json={
                "model": SUANLI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
            },
            timeout=(10, 240),
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    return _retry(call)


def oc_usage_snippet():
    """Optional guard: read OpenCode Go usage (to verify jev-1.13-free is really free)."""
    try:
        r = requests.get(OC_USAGE_URL,
                         headers={"Authorization": "Bearer " + os.environ["OPENCODE_API_KEY"]},
                         timeout=30)
        return r.text[:600]
    except Exception as e:  # noqa: BLE001
        return f"usage probe failed: {e}"


# ---------------------------------------------------------------- normalization

_ZH_DIGIT = "零一二三四五六七八九"
_NUM_RE = re.compile(r"\d+")


def arabic_int_to_zh(n):
    if n < 10:
        return _ZH_DIGIT[n]
    if n < 20:
        return "十" + ("" if n % 10 == 0 else _ZH_DIGIT[n % 10])
    for val, unit in [(10**8, "亿"), (10**4, "万"), (1000, "千"), (100, "百"), (10, "十")]:
        if n >= val:
            q, r = divmod(n, val)
            head = arabic_int_to_zh(q) + unit
            if r == 0:
                return head
            if r * 10 < val:  # e.g. 205 -> 二百零五
                return head + "零" + arabic_int_to_zh(r)
            return head + arabic_int_to_zh(r)
    return str(n)


_EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
            "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
            "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
            "eighty", "ninety"]


def en_int_to_words(n):
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        t = _EN_TENS[n // 10]
        return t + ("-" + _EN_ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _EN_ONES[n // 100] + " hundred" + (" " + en_int_to_words(n % 100) if n % 100 else "")
    if n < 10**6:
        return en_int_to_words(n // 1000) + " thousand" + (" " + en_int_to_words(n % 1000) if n % 1000 else "")
    return str(n)


def norm_zh(text):
    """ITN-proof normalize: arabic digits -> chinese numerals, keep CJK only."""
    def sub(m):
        try:
            return arabic_int_to_zh(int(m.group()))
        except Exception:  # noqa: BLE001
            return ""
    text = _NUM_RE.sub(sub, str(text))
    return "".join(re.findall(r"[\u3400-\u9fff]", text))


def norm_en(text):
    def sub(m):
        try:
            return " " + en_int_to_words(int(m.group())) + " "
        except Exception:  # noqa: BLE001
            return " "
    text = _NUM_RE.sub(sub, str(text).lower())
    text = text.replace("'", "")
    text = re.sub(r"[^a-z ]+", " ", text)
    return " ".join(text.split())


# ---------------------------------------------------------------- alignment / metrics

def bad_positions(hyp_seq, ref_seq):
    """Ground-truth error positions in hyp: non-equal blocks + deletion adjacency."""
    import difflib
    sm = difflib.SequenceMatcher(None, ref_seq, hyp_seq, autojunk=False)
    bad = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        bad.update(range(j1, j2))            # replace / insert positions in hyp
        if tag == "delete" and hyp_seq:       # ref-side chars missing in hyp
            bad.add(min(j1, len(hyp_seq) - 1))
    return sorted(bad)


def changed_positions(old_seq, new_seq):
    """Positions of old_seq that changed (aligned), for over-correction counting."""
    import difflib
    sm = difflib.SequenceMatcher(None, old_seq, new_seq, autojunk=False)
    ch = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            ch.update(range(i1, i2))
    return sorted(ch)


def levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def err_rate(ref_seq, hyp_seq):
    if not ref_seq:
        return 0.0 if not hyp_seq else 1.0
    return levenshtein(list(ref_seq), list(hyp_seq)) / len(ref_seq)
