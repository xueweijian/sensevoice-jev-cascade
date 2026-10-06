# Round 7 过程记录

## 目标

用户指出 Round 6 只把前两名 ASR 接了冠军纠错，要求把没有跑过的免费模型也跑完，直接回答：**哪个免费 ASR 接纠错后提升，哪个变差。**

## 费用边界

Qwen3-ASR-1.7B 已确认收费 ¥0.000220/秒输入音频，Round 7 从代码和 workflow 中完全排除。Round 7 只调用：

- FunAudioLLM/SenseVoiceSmall（免费）
- XingChenAGI/XingChenASR-V3.2（免费）
- XingChenAGI/XingChenASR-V3.2-Ultra（免费）
- XingChenAGI/XingChenASR-Diarize-V3.0（免费）

workflow 在结果中断言 `free_engines` 只能是这四个 key，防止付费模型混入。

## 实验步骤

1. 使用 Round 4 同一 20 条考卷：10 条脏音频 + 10 条原 SenseVoice 净音频。
2. 每个免费 ASR 每条音频只调用一次，保存 raw text、duration、segments、speaker 元数据。
3. Diarize 不把 `1:` 之类 speaker 标签计入文本错误，改用每个 segment 的 `text` 拼接后评分；原始 segments 保留在 JSON。
4. 所有四个 ASR 文本统一关闭 CSC 门控，接同一个冠军纠错：4.1flash、`reasoning_effort:none`、裸改→验证两遍。
5. 每个 ASR+纠错重复 2 次，统计总体、脏句、净句、中文、英文、改善/持平/恶化、调用数和延迟。
6. Qwen 没有调用。

## 实施中的安全措施

- Round 6 workflow 曾因文档提交误触发，已手动禁用。
- Round 7 单独 workflow 只做 `workflow_dispatch`，不会随普通 push 触发。
- `round7.py` 的 `FREE_ENGINES` 常量只有四个免费模型；Qwen 只出现在解释性注释中。
- 运行后结果断言检查，保证 Qwen key 不在实际结果集合。

## 结果位置

- 原始逐句数据：`experiments/round7/round7.json`
- 汇总表：`experiments/round7/round7-summary.md`
- 数据分析：`docs/round7-analysis.md`

## 重要解释

Round 7 的 10 条 clean 音频是“对 SenseVoice 干净”，换 ASR 后可能不再干净。因此不能只看 clean 组是否被修改，要分别记录新 ASR 的 raw error 和纠错后的 error；否则会把换 ASR 新产生的错误错误地归咎于纠错器。
