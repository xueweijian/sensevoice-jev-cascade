"""ASR layer: SenseVoice via SiliconFlow, long-audio chunking via ffmpeg."""
import os
import re
import subprocess
import tempfile
import time

import requests

from .config import Config


def _post_asr(path, cfg):
    key = os.environ["SILICONFLOW_API_KEY"]
    with open(path, "rb") as f:
        r = requests.post(
            cfg.asr_url,
            headers={"Authorization": "Bearer " + key},
            files={"file": (os.path.basename(path), f)},
            data={"model": cfg.asr_model},
            timeout=(10, cfg.timeout))
    r.raise_for_status()
    return r.json()["text"]


def transcribe(path, cfg, log=print):
    """Transcribe an audio file. Splits long audio at silences (ffmpeg)
    into <= chunk_max_seconds pieces and stitches transcripts."""
    dur = _duration(path)
    if dur is None or dur <= cfg.chunk_max_seconds:
        return _retry(lambda: _post_asr(path, cfg), cfg), {"chunks": 1, "duration_s": dur}

    with tempfile.TemporaryDirectory() as td:
        pieces = _split_on_silence(path, cfg.chunk_max_seconds, td)
        texts = []
        for i, piece in enumerate(pieces):
            t = _retry(lambda p=piece: _post_asr(p, cfg), cfg)
            texts.append(t.strip())
            log(f"  [asr] chunk {i + 1}/{len(pieces)} done")
        return " ".join(texts), {"chunks": len(pieces), "duration_s": dur}


def _retry(fn, cfg):
    last = None
    for k in range(cfg.retries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (k + 1))
    raise last


def _duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def _split_on_silence(path, max_sec, outdir):
    """Split at detected silences; falls back to fixed cuts."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path, "-af",
             "silencedetect=noise=-35dB:d=0.6", "-f", "null", "-"],
            capture_output=True, text=True, timeout=300)
        marks = [float(m) for m in re.findall(
            r"silence_start: ([0-9.]+)", proc.stderr)]
        dur = _duration(path) or 0
    except Exception:  # noqa: BLE001
        marks, dur = [], 0
    cuts = _greedy_cutpoints(marks, dur, max_sec)
    if not cuts:
        n = int(dur // max_sec) + 1
        step = dur / n
        cuts = [step * i for i in range(1, n)]
    pieces = []
    prev = 0.0
    for c in list(cuts) + [dur]:
        seg = os.path.join(outdir, f"part{len(pieces):03d}.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", str(max(prev - 0.15, 0)), "-to", str(c),
                        "-i", path, "-ar", "16000", "-ac", "1", seg],
                       check=True, timeout=300)
        pieces.append(seg)
        prev = c
    return [p for p in pieces if os.path.getsize(p) > 8000]


def _greedy_cutpoints(silences, dur, max_sec):
    """Pick silence points so every chunk <= max_sec when possible."""
    if not dur:
        return []
    pts, last = [], 0.0
    while dur - last > max_sec:
        horizon = last + max_sec
        cands = [s for s in silences if last + 5 < s <= horizon]
        cut = cands[-1] if cands else horizon
        pts.append(cut)
        last = cut
    return pts
