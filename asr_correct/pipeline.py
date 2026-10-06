"""Orchestrator: audio/text -> ASR -> segment -> correct -> verify -> report."""
import concurrent.futures as cf
import os
import time

from .asr import transcribe
from .config import Config
from .correct import correct_sentence
from .segment import split_sentences, windows


def run(text=None, audio_path=None, cfg=None, log=print):
    """Process one document. Returns a result dict (see report.py)."""
    cfg = cfg or Config()
    t_start = time.time()
    result = {"config": cfg.to_dict(), "audio": audio_path,
              "asr": None, "sentences": [], "stats": {}}

    if audio_path:
        t0 = time.time()
        raw, info = transcribe(audio_path, cfg, log=log)
        result["asr"] = {"text": raw, "latency_s": round(time.time() - t0, 2), **info}
        text = raw
    result["input_text"] = text or ""

    sents = split_sentences(text, cfg.sentence_max_chars, cfg.sentence_max_words)
    result["n_sentences"] = len(sents)
    log(f"[segment] {len(sents)} sentences, window={cfg.window}")

    def work(win):
        editable, context = win
        ctx_map = {i: s for i, s in sents if i in context}
        out = {}
        for i in editable:
            sentence = dict(sents)[i]
            if cfg.window > 1 and ctx_map:
                ctx = " ".join(ctx_map[j] for j in sorted(ctx_map))
                # context is advisory only: correct the single editable sentence
                r = correct_sentence(sentence, cfg, log=log)
                r["context_used"] = True
            else:
                r = correct_sentence(sentence, cfg, log=log)
            out[i] = r
        return out

    per_sentence = {}
    if cfg.workers > 1 and len(sents) > 1:
        with cf.ThreadPoolExecutor(max_workers=cfg.workers) as ex:
            for part in ex.map(work, windows(sents, cfg.window, cfg.window_overlap)):
                per_sentence.update(part)
    else:
        for part in map(work, windows(sents, cfg.window, cfg.window_overlap)):
            per_sentence.update(part)

    corrected = [per_sentence[i]["final"] for i, _ in sents]
    result["sentences"] = [per_sentence[i] for i, _ in sents]
    result["corrected_text"] = _join(corrected, result["input_text"])
    result["stats"] = _stats(result, t_start)
    log(f"[done] edits={result['stats']['total_edits']} "
        f"guards={result['stats']['guard_events']} "
        f"wall={result['stats']['wall_s']}s")
    return result


def _join(corrected, original):
    """Join sentences; keep original's terminator style (zh: no space)."""
    is_cjk = sum(1 for c in original[:200] if "\u4e00" <= c <= "\u9fff")
    is_ascii = sum(1 for c in original[:200] if c.isascii() and c.isalpha())
    sep = "" if is_cjk >= is_ascii else " "
    text = sep.join(corrected)
    return text if text.endswith(("。", "！", "？", ".", "!", "?")) or not text \
        else text


def _stats(result, t_start):
    sents = result["sentences"]
    lats = [l for s in sents for l in s.get("lat", [])]
    lats.sort()
    return {
        "total_edits": sum(len(s.get("edits", [])) for s in sents),
        "corrected_sentences": sum(1 for s in sents if s["final"] != s["orig"]),
        "guard_events": sum(len(s.get("guards", [])) for s in sents),
        "fallback_events": sum(1 for s in sents if s.get("used_fallback")),
        "llm_calls": sum(s.get("calls", 0) for s in sents),
        "lat_p50": lats[len(lats) // 2] if lats else None,
        "lat_p99": lats[int(len(lats) * 0.99) - 1] if lats else None,
        "wall_s": round(time.time() - t_start, 2),
    }
