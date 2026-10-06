"""Pipeline configuration. CLI args > env > defaults."""
import os
from dataclasses import dataclass, field, asdict


@dataclass
class Config:
    # ---- ASR ----
    asr_url: str = "https://api.siliconflow.cn/v1/audio/transcriptions"
    asr_model: str = "FunAudioLLM/SenseVoiceSmall"
    chunk_max_seconds: float = 60.0   # long-audio split target

    # ---- LLM registry ----
    # d41n  = opencode deepseek-v4.1-flash, thinking OFF  (champion, R4 E3)
    # v4f   = suanli deepseek-v4-flash-0731-free + few-shot (fallback, R4 E5)
    # d41t  = opencode 4.1-flash thinking ON (ONLY for constrained jobs)
    llm_primary: str = "d41n"
    llm_fallback: str = "v4f"
    llm_verify: str = "d41n"          # verifier rides the primary by default
    verify_enabled: bool = True

    # ---- guardrails (R4-proven thresholds) ----
    max_edit_ratio: float = 0.15      # per-sentence edit budget (>=2 units)
    min_len_ratio: float = 0.75       # below -> deletion-suspect, reject edit
    max_len_ratio: float = 1.4        # above -> rewrite-suspect, reject edit
    empty_retries: int = 1

    # ---- segmentation ----
    sentence_max_chars: int = 80      # zh chars
    sentence_max_words: int = 30      # en words
    window: int = 1                   # sentences per correction call
    window_overlap: int = 1           # context-only sentences at both ends

    # ---- Layer-0 gate (R5: -55% LLM calls, zero quality delta) ----
    gate_enabled: bool = True
    gate_threshold: float = 0.5       # CSC per-char confidence to flag
    gate_en_min_len: int = 4          # en: ignore words shorter than this

    # ---- runtime ----
    workers: int = 2
    retries: int = 3
    timeout: float = 300.0

    def model_spec(self, model_id):
        if model_id == "d41n":
            return {"url": "https://opencode.ai/zen/go/v1/chat/completions",
                    "key_env": "OPENCODE_API_KEY", "model": "deepseek-v4.1-flash",
                    "max_tokens": 1500, "reasoning_effort": "none",
                    "session_header": "asr-correct"}
        if model_id == "d41t":
            return {"url": "https://opencode.ai/zen/go/v1/chat/completions",
                    "key_env": "OPENCODE_API_KEY", "model": "deepseek-v4.1-flash",
                    "max_tokens": 4000, "session_header": "asr-correct"}
        if model_id == "v4f":
            return {"url": "https://api.suanli.cn/v1/chat/completions",
                    "key_env": "SUANLI_API_KEY",
                    "model": "deepseek/deepseek-v4-flash-0731-free",
                    "max_tokens": 1200, "fewshot": True}
        raise ValueError(f"unknown model id: {model_id}")

    def has_key(self, model_id):
        return bool(os.environ.get(self.model_spec(model_id)["key_env"]))

    def to_dict(self):
        return asdict(self)
