---
name: asr-correct
description: ASR转写纠错生产管线（R4-R7四轮实验冠军方案）。输入音频或已有转写文本，输出纠错后的文本+逐句审计报告。适用于"帮我纠错这段转写"、"修复ASR错字"、"修转写"、"纠正语音识别错误"等场景。支持中英文、长音频自动切分、说话人日志模型选择。
---

# ASR 转写纠错

## 这是什么

经过 7 轮实验（R1-R7）验证的 ASR 转写纠错管线，融合了 RLLM-CF 论文验证遍、宝玉方案防删减护栏、transcript-fixer 保守哲学，以及多轮实测标定的阈值。

核心架构：`Layer-0 门控（免费本地小模型快筛）→ 4.1flash(关思考) 裸改+验证两遍流 → 三重护栏 → 兜底链`

实测成绩：脏句 -62%、零恶化句、净句零损伤、平均 0.65 次 LLM 调用/句、全程免费。

## 快速使用

代码位于 `/var/minis/workspace/sensevoice-jev-cascade/asr_correct/`

```bash
cd /var/minis/workspace/sensevoice-jev-cascade

# 音频文件 → 纠错文本（支持 wav/mp3/flac/m4a，长音频自动按静音切分）
python3 -m asr_correct meeting.wav -o /tmp/out/

# 已有转写文本 → 纠错
python3 -m asr_correct transcript.txt -o /tmp/out/ --mode text

# 输出三个文件：
# /tmp/out/corrected.txt   ← 纠错后的文本
# /tmp/out/report.json     ← 逐句审计（原文/改后/编辑/护栏触发）
# /tmp/out/diff.md         ← 人读对照表
```

需要环境变量：`SILICONFLOW_API_KEY`（ASR）+ `OPENCODE_API_KEY`（主 LLM）或 `SUANLI_API_KEY`（兜底）。已在 Minis 环境配置。

## ASR 模型选择（R7 实测推荐）

| 场景 | 模型 | 命令参数 |
|---|---|---|
| 默认（免费，链路最成熟） | SenseVoiceSmall | 不加参数 |
| 免费+最低错误率（中文只出建议） | XingChen-V3.2 | `--asr-model XingChenAGI/XingChenASR-V3.2` |
| 必须统一自动纠错（免费最稳） | XingChen-Ultra | `--asr-model XingChenAGI/XingChenASR-V3.2-Ultra` |
| 说话人日志（免费） | XingChen-Diarize | `--asr-model XingChenAGI/XingChenASR-Diarize-V3.0` |
| 质量最高（**付费**） | Qwen3-ASR-1.7B | `--asr-model Qwen/Qwen3-ASR-1.7B` ⚠️¥0.00022/秒 |

⚠️ Qwen3-ASR **收费**，不传就不花钱。日韩音频走 SenseVoice；方言走 XingChen。

## LLM 模型选择

| 模型 | 用法 | 说明 |
|---|---|---|
| `--model d41n`（默认） | 4.1flash 关思考 | 冠军方案，Go 会员免费，p99<3s |
| `--model v4f` | suanli v4-flash+few-shot | Go 额度耗尽时兜底，免费 |
| `--model d41t` | 4.1flash 开思考 | ⚠️仅约束岗位用，自由岗位会跑偏 |

## 中英文行为差异（R7 实测关键结论）

- **英文**：自动纠错稳定收益 -50%~-72%，放心用
- **中文**：在 XingChen-V3.2 底座上**只出建议不自动改**（越修越差）；在 SenseVoice 底座上自动纠错 -44% 有收益
- 中文同音字是纯文本判别先天盲区，需要声学证据才能根治

## 常用参数

```bash
--mode text          # 输入是纯文本而非音频
--no-verify          # 跳过验证遍（快1s，少一道保险）
--no-gate            # 关闭 Layer-0 门控（多花 LLM 调用）
--no-fallback        # 禁用兜底链（准实时场景减延迟）
--workers 3          # 句级并发
--max-chunk-sec 60   # 长音频切分目标时长
--quiet              # 安静模式
```

## 审计报告解读

`report.json` 的 `stats` 字段：

- `total_edits`：总编辑数（改了几个字/词）
- `corrected_sentences`：被修改的句子数
- `gated_out`：被门控放行（0 调用直接通过的句子数）
- `llm_calls`：总 LLM 调用数（越低越省钱）
- `fallback_events`：兜底触发次数（Go 额度不够了会涨）
- `lat_p50/p99`：延迟分位数

单句字段：`orig`（原文）、`final`（改后）、`edits`（编辑列表）、`guards`（护栏触发记录）、`gated`（是否被门控放行）。

## 护栏机制（R4-R5 标定，勿随意放宽）

1. 空输出重试 ×1
2. 长度比窗口 [0.75, 1.4]（防删减/防重写）
3. 编辑量预算：每句 max(2, 15% 字数)
4. 净句零损伤是硬指标（回灌干净转写看 `corrected_sentences` 应为 0）

## 实验背景

完整数据与结论在仓库 `docs/findings.md`（21 条编号结论）+ `experiments/round{1-7}/`（七轮原始数据）。

GitHub: https://github.com/xueweijian/sensevoice-jev-cascade
