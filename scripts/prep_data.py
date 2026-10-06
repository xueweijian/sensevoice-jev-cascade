#!/usr/bin/env python3
"""Download labeled audio + build manifests.

zh: AISHELL-1 (HF official repo, per-speaker tarballs + transcript index)
en: LibriSpeech test-clean (OpenSLR, reader 1272 only)
Also builds the pinyin->chars index from the AISHELL transcript charset
(domain-matched candidate table for same-sound backfill; pure text tool, no model).
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tarfile

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_ec import norm_zh  # noqa: E402

HF_AISHELL = "https://huggingface.co/datasets/AISHELL/AISHELL-1/resolve/main"
LIBRI_URL = "https://www.openslr.org/resources/12/test-clean.tar.gz"
ZH_SPEAKERS = ["S0002", "S0003"]
ZH_CAP = 120   # candidates into manifest
EN_CAP = 120


def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print("cached:", path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print("downloading:", url, "->", path)
    tmp = path + ".part"
    with requests.get(url, stream=True, timeout=(15, 600)) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                if chunk:
                    f.write(chunk)
    os.replace(tmp, path)
    print("  size:", os.path.getsize(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/work")
    args = ap.parse_args()
    work = args.work
    dl = os.path.join(work, "dl")
    os.makedirs(dl, exist_ok=True)

    # ---------------- zh: transcript index ----------------
    trans_path = os.path.join(dl, "aishell_transcript_v0.8.txt")
    download(HF_AISHELL + "/data_aishell/transcript/aishell_transcript_v0.8.txt", trans_path)
    zh_ref = {}
    for line in open(trans_path, encoding="utf-8"):
        parts = line.strip().split()
        if len(parts) >= 2:
            zh_ref[parts[0]] = "".join(parts[1:])
    print("zh transcript entries:", len(zh_ref))

    # ---------------- pinyin index from domain charset ----------------
    from pypinyin import lazy_pinyin
    charset = sorted(set("".join(zh_ref.values())) - {" "})
    py_index = {}
    for ch in charset:
        try:
            py = lazy_pinyin(ch)[0]
        except Exception:  # noqa: BLE001
            continue
        py_index.setdefault(py, []).append(ch)
    with open(os.path.join(work, "pinyin_index.json"), "w", encoding="utf-8") as f:
        json.dump(py_index, f, ensure_ascii=False)
    print("charset:", len(charset), "pinyin groups:", len(py_index))

    # ---------------- zh: speaker tarballs ----------------
    wav_root = os.path.join(work, "aishell")
    done_flag = os.path.join(wav_root, "done")
    if not os.path.exists(done_flag):
        for spk in ZH_SPEAKERS:
            tgz = os.path.join(dl, spk + ".tar.gz")
            download(HF_AISHELL + "/data_aishell/wav/" + spk + ".tar.gz", tgz)
            print("extracting", tgz)
            with tarfile.open(tgz) as tf:
                tf.extractall(wav_root)
        open(done_flag, "w").write("ok")
    zh_wavs = sorted(glob.glob(os.path.join(wav_root, "**", "*.wav"), recursive=True))
    print("zh wavs:", len(zh_wavs))

    # ---------------- en: LibriSpeech reader 1272 ----------------
    en_root = os.path.join(work, "librispeech")
    en_done = os.path.join(en_root, "done")
    if not os.path.exists(en_done):
        tgz = os.path.join(dl, "test-clean.tar.gz")
        download(LIBRI_URL, tgz)
        print("extracting reader 1272 only")
        with tarfile.open(tgz) as tf:
            members = [m for m in tf.getmembers() if "/1272/" in m.name]
            tf.extractall(en_root, members=members)
        open(en_done, "w").write("ok")
    if not subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0:
        subprocess.run(["sudo", "apt-get", "update", "-y"], check=True)
        subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"], check=True)
    for flac in sorted(glob.glob(os.path.join(en_root, "**", "*.flac"), recursive=True)):
        wav = flac[:-5] + ".wav"
        if not os.path.exists(wav):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", flac,
                            "-ar", "16000", "-ac", "1", wav], check=True)
    en_wavs = sorted(glob.glob(os.path.join(en_root, "**", "*.wav"), recursive=True))
    en_ref = {}
    for tpath in glob.glob(os.path.join(en_root, "**", "*.trans.txt"), recursive=True):
        for line in open(tpath, encoding="utf-8"):
            parts = line.strip().split()
            if len(parts) >= 2:
                en_ref[parts[0]] = " ".join(parts[1:])
    print("en wavs:", len(en_wavs), "en refs:", len(en_ref))

    # ---------------- manifest ----------------
    rows = []
    for w in zh_wavs:
        uid = os.path.splitext(os.path.basename(w))[0]
        if uid in zh_ref and 10_000 < os.path.getsize(w) < 2_000_000 and norm_zh(zh_ref[uid]):
            rows.append({"id": uid, "wav": w, "ref": zh_ref[uid], "lang": "zh"})
    rows = rows[:ZH_CAP]
    n_zh = len(rows)
    for w in en_wavs:
        uid = os.path.splitext(os.path.basename(w))[0]
        if uid in en_ref and 10_000 < os.path.getsize(w) < 2_000_000:
            rows.append({"id": uid, "wav": w, "ref": en_ref[uid], "lang": "en"})
    rows = rows[:n_zh + EN_CAP]
    out = os.path.join(work, "manifest.all.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("manifest:", out, "rows:", len(rows), "(zh", n_zh, ")")


if __name__ == "__main__":
    main()
