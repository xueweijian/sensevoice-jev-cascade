"""Sentence segmentation + sliding windows."""
import re

_END = "。！？!?；;….…"


def split_sentences(text, max_chars=80, max_words=30):
    """Split on terminators; long segments are hard-split by length.
    Returns (index, sentence) pairs preserving order; spaces collapsed."""
    text = text.replace("\r", "\n").strip()
    if not text:
        return []
    parts, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _END:
            parts.append(buf)
            buf = ""
    if buf.strip():
        parts.append(buf)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if _is_latin(p):
            out += _hard_split_words(p, max_words)
        else:
            out += _hard_split_chars(p, max_chars)
    return [(i, s) for i, s in enumerate(out)]


def _is_latin(s):
    latin = sum(1 for c in s if c.isascii() and c.isalpha())
    cjk = len(re.findall(r"[\u3400-\u9fff]", s))
    return latin > cjk


def _hard_split_chars(seg, n):
    seg = re.sub(r"\s+", "", seg)
    if len(seg) <= n:
        return [seg]
    return [seg[i:i + n] for i in range(0, len(seg), n)]


def _hard_split_words(seg, n):
    words = seg.split()
    if len(words) <= n:
        return [seg]
    return [" ".join(words[i:i + n]) for i in range(0, len(words), n)]


def lang_of(text):
    return "en" if _is_latin(text) else "zh"


def windows(sentences, size=1, overlap=1):
    """Yield (editable_indices, context_indices) windows.
    size=1 -> plain per-sentence mode (R4-proven optimum)."""
    if size <= 1:
        for i, s in sentences:
            yield [i], []
        return
    step = max(size - 2 * overlap, 1)
    for start in range(0, len(sentences), step):
        chunk = sentences[start:start + size]
        if not chunk:
            break
        editable = [i for i, _ in chunk[overlap:len(chunk) - overlap]] or \
                   [chunk[0][0]]
        context = [i for i, _ in chunk if i not in editable]
        yield editable, context
