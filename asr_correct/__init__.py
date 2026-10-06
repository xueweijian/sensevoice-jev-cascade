"""ASR error-correction production pipeline.

Champion configuration (experiments/round4): two-pass correction with
deepseek-v4.1-flash (thinking OFF via reasoning_effort:"none") —
pass 1 correct, pass 2 verify — plus guardrails proven by round 4:
clean-clip zero damage, zero worsened sentences, p99 < 3s.

    python -m asr_correct audio.wav                 # audio -> corrected text
    python -m asr_correct transcript.txt --mode text
    python -m asr_correct dir/ -o out/ --workers 2

Requires env: SILICONFLOW_API_KEY (ASR), OPENCODE_API_KEY (primary LLM),
optional SUANLI_API_KEY (fallback LLM).
"""
__version__ = "1.0.0"
