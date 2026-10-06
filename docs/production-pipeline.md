# 生产管线 asr_correct（Round 4/5 冠军方案的工程化）

两遍纠错流水线：**ASR 转写 → 4.1flash(关思考) 裸改 → 同模型验证官复核
→ 三重护栏**。R4 实测：脏句 -62%、零恶化句、净句零损伤、p50 1.3s / p99 2.9s。

默认 ASR 仍是硅基流动的免费 `FunAudioLLM/SenseVoiceSmall`。Round 6 验证了
`Qwen/Qwen3-ASR-1.7B` 质量明显更高，但它是**付费模型**（在线推理价格
¥0.000220/秒输入音频时长），不是默认选项；只有明确批准成本时才用
`--asr-model Qwen/Qwen3-ASR-1.7B`。

## 快速上手

```bash
export SILICONFLOW_API_KEY=...   # ASR
export OPENCODE_API_KEY=...      # 主 LLM（4.1flash，Go 会员）
export SUANLI_API_KEY=...        # 可选：兜底 LLM

# 音频 → 纠错文本（支持 wav/mp3/flac/m4a，长音频自动按静音切分）
python -m asr_correct meeting.wav -o out/

# 已有转写文本 → 纠错
python -m asr_correct transcript.txt -o out/ --mode text

# 批量目录 + 3 并发
python -m asr_correct *.wav -o out/ --workers 3

# 输出：out/corrected.txt（成品文本） out/report.json（逐句审计）
#       out/diff.md（人读对照表）
```

## 架构（含 R5 新增 Layer-0 门控）

```
音频 ──ffmpeg 静音检测（>60s 才切）──→ SenseVoice API（硅基流动）
        ↓ 转写文本
      分句（中英自适应，长句硬切；默认单句粒度 = R4 实测最优）
        ↓
      Layer-0 门控（R5：调用 -55%，质量零损失）
      zh: MacBERT4CSC 逐字疑点 / en: 词表查非词 → 无疑点直接放行（0 调用）
        ↓ 疑点句
      Pass1 裸改：4.1flash（reasoning_effort:"none"）
        ↓ 护栏①：空输出重试 / 长度比窗口 [0.75, 1.4] / 编辑量预算
      Pass2 验证：同模型当审计员，逐项复核改动，恢复误改
        ↓ 护栏②：对原始句再过一遍（不过则保留 Pass1 结果）
      兜底链：主模型失败/被护栏拒 → v4flash + few-shot（R4 唯一零净损的免费形态）
        ↓ 全部失败 → 保留原句并标记（"看得见的乱码好过流畅的错猜"）
      corrected.txt + report.json + diff.md
```

## 配置项（CLI / Config）

| 项 | 默认 | 说明 |
|---|---|---|
| `--model` | d41n | d41n=4.1flash关想 / v4f=v4flash+fewshot / d41t=4.1flash想（仅约束岗位） |
| `--no-verify` | 关 | 跳过 Pass2（快 ~1s，少一道保险，不建议生产关） |
| `--window` | 1 | 每次调用带几句（R4 实测 >1 无增益且慢，保留作成本开关） |
| `--max-chunk-sec` | 60 | 长音频切分目标时长（ffmpeg 静音优先，兜底定点切） |
| `--workers` | 2 | 句级并发（注意 API 限速） |
| Config.min_len_ratio / max_edit_ratio | 0.75 / 0.15 | 护栏阈值（R4 标定） |

## 护栏规范（R4 标定，勿随意放宽）

1. **空输出重试** ×1（关想的 4.1f 几乎不出空；想模式会——所以想模式别上自由岗位）
2. **长度比窗口 [0.75, 1.4]**：低于 = 删减嫌疑，高于 = 重写嫌疑 → 拒收本轮
   修正、试兜底模型；全拒则保留原句
3. **编辑量预算**：每句 max(2, 15% 字数)，超 3 倍直接拒
4. **净句零损伤是硬指标**：上线后定期用干净转写回灌 report.json，看
   `stats.corrected_sentences` 应为 0

## 速率与成本

- 每句 2 次调用（改+验），p50 ≈ 1.3s/句（2 并发下吞吐 ≈ 1.5 句/s）
- 全免费额度内：SenseVoice（硅基流动）+ 4.1flash（OpenCode Go 会员；
  `reasoning_effort:"none"` 后单句输出 token 极少）+ v4flash 兜底（suanli）
- Go 额度耗尽自动落 v4f 兜底（report.json 的 `used_fallback` 可监控比例）

## 部署建议

- 离线批处理：直接 `python -m asr_correct`，输出 report.json 入库审计
- 准实时（字幕）：`--no-fallback`（少一层重试延迟）+ workers=1~2，
  p99 < 3s
- ASR 选择：默认 `FunAudioLLM/SenseVoiceSmall`（免费）；质量优先且明确接受
  按量费用时，可用 `--asr-model Qwen/Qwen3-ASR-1.7B`（¥0.000220/秒输入音频时长）。
  Round6 只做过一次付费质量实验，后续不自动调用 Qwen。
- 需要时间戳+说话人日志时可试 `XingChenAGI/XingChenASR-Diarize-V3.0`；
  但 Round6 测试显示其中文识别质量明显差，不建议作为默认识别底座。
- 升级路径：①业务口语音频进来后先测"去口癖"需求 ②若真实音频错误率高到
  提示词路线失灵（ASR-EC 预警线），启动 LoRA 微调二期
