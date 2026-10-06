"""CLI: python -m asr_correct <files...>"""
import argparse
import os
import sys

from .config import Config
from .pipeline import run
from .report import write_outputs


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="asr_correct",
        description="ASR 纠错生产管线：SenseVoice → 4.1flash(关思考)两遍纠错 → 护栏")
    ap.add_argument("inputs", nargs="+", help="音频文件（wav/mp3/flac/m4a）或已转写文本(.txt)")
    ap.add_argument("-o", "--outdir", default="out")
    ap.add_argument("--mode", choices=["auto", "audio", "text"], default="auto")
    ap.add_argument("--model", default=None, help="d41n | v4f | d41t（默认 d41n）")
    ap.add_argument("--fallback-model", default=None)
    ap.add_argument("--no-verify", action="store_true", help="跳过验证遍（快但少一道保险）")
    ap.add_argument("--no-fallback", action="store_true")
    ap.add_argument("--window", type=int, default=1, help="每词调用句子数（默认1，R4最优）")
    ap.add_argument("--no-gate", action="store_true", help="关闭 Layer-0 门控（R5 默认开）")
    ap.add_argument("--gate-threshold", type=float, default=0.5)
    ap.add_argument("--asr-model", default=None,
                    help="ASR engine (default FunAudioLLM/SenseVoiceSmall；R6 推荐 "
                         "Qwen/Qwen3-ASR-1.7B（付费实验模型；zh -68%/en -86%）)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-chunk-sec", type=float, default=60.0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    cfg = Config()
    if args.model:
        cfg.llm_primary = args.model
    if args.fallback_model:
        cfg.llm_fallback = args.fallback_model
    if args.no_fallback:
        cfg.llm_fallback = ""
    cfg.verify_enabled = not args.no_verify
    cfg.gate_enabled = not args.no_gate
    cfg.gate_threshold = args.gate_threshold
    if args.asr_model:
        cfg.asr_model = args.asr_model
    cfg.window = max(1, args.window)
    cfg.workers = max(1, args.workers)
    cfg.chunk_max_seconds = args.max_chunk_sec

    missing = [k for k in ("SILICONFLOW_API_KEY",) if not os.environ.get(k)]
    if not os.environ.get("OPENCODE_API_KEY") and not os.environ.get("SUANLI_API_KEY"):
        missing.append("OPENCODE_API_KEY|SUANLI_API_KEY(至少一个)")
    if missing:
        print("缺少环境变量:", ", ".join(missing), file=sys.stderr)
        return 2

    rc = 0
    for path in args.inputs:
        mode = args.mode
        if mode == "auto":
            mode = "text" if path.lower().endswith((".txt", ".md")) else "audio"
        print(f"=== {path} (mode={mode}) ===")
        try:
            if mode == "text":
                text = open(path, encoding="utf-8").read()
                result = run(text=text, cfg=cfg, log=(lambda *_: None) if args.quiet else print)
            else:
                result = run(audio_path=path, cfg=cfg,
                             log=(lambda *_: None) if args.quiet else print)
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {path}: {e!r}", file=sys.stderr)
            rc = 1
            continue
        base = os.path.splitext(os.path.basename(path))[0]
        outdir = os.path.join(args.outdir, base) if len(args.inputs) > 1 else args.outdir
        write_outputs(result, outdir, quiet=args.quiet)
        st = result["stats"]
        print(f"[stats] edits={st['total_edits']} calls={st['llm_calls']} "
              f"guards={st['guard_events']} fallback={st['fallback_events']} "
              f"p50={st['lat_p50']}s wall={st['wall_s']}s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
