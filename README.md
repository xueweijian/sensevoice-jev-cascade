# sensevoice-jev-cascade

ASR 错字纠正级联实验（smoke scale）：**一次 ASR、纯文本判别、同音约束回填**。

## 架构

```
音频 ──→ SiliconFlow SenseVoiceSmall（唯一一次前向，无置信度可用）
          ↓ 转写文本
      Jev 兼容判别（硅基流动 /v1/systemone，纯文本 state）
        has_error(noul) + 逐字 noul×N + 错字数(score)
          ↓ 可疑字定位
      同音候选表：pypinyin（纯文本工具，非模型）
          ↓
      ① 判别模型 choice 选字 → 高置信直接回填
      ② 低置信 → LLM 兜底（suanli deepseek-v4-flash，JSON 强约束，
         候选锁死同音集，温度 0）
```

判别模型横向对比：`Kev-4B` / `SemIf` / `diffusiongemma`（硅基流动免费），
可选 `jev-1.13-free`（OpenCode，带用量护栏验证免费性）。

## 对照组

| 组 | 配置 | 预期 |
|---|---|---|
| A | 原始 ASR | 基线 |
| B | 裸 LLM 全文纠错（无门控无约束） | 过度纠错 |
| D | 门控 + 定位 + 约束回填 | CER ≤ A 且过度纠错 < B |

**成立判据**：D 的错误率 ≤ A、且 D 的过度纠错数 < B → 级联方向成立。

## 方法要点

- **选材筛查**：语料是朗读级干净音频，SenseVoice 错误率低。先扫候选、只保留
  真有错字的 clip（每语言 5 条），否则纠错实验无从谈起。
- **真值对齐**：错字位置 = 归一化后 hypothesis 与 reference 的字符对齐
  （difflib）非 equal 块，用作检测 P/R 的 ground truth。
- **ITN 归一化**：SenseVoice 输出阿拉伯数字（"9点"）、AISHELL 标注是中文数字
  （"九点"），不做转换会制造海量假错字。中文数字/英文数字词双向转换后再对齐。
- **诚实边界**：纯文本判别看不到声学证据，"文本上双向通顺的同音替换"是先天
  盲区（SoftCorrect 消融：纯文本检测只有融合声学的一半）。本实验测量这个
  边界在哪，而非假装它不存在。

## 数据

- zh：[AISHELL-1](https://huggingface.co/datasets/AISHELL/AISHELL-1)（Apache-2.0，
  按说话人分卷 + transcript 索引）
- en：[LibriSpeech test-clean](https://www.openslr.org/12)（reader 1272）

音频与数据不进 git，CI 内现取 + cache。

## 复现

```
python scripts/prep_data.py --work /tmp/work
python scripts/screen.py --work /tmp/work --need 5
python scripts/run_experiment.py --manifest /tmp/work/manifest.smoke.jsonl \
  --pinyin-index /tmp/work/pinyin_index.json --out results
```

需要环境变量：`SILICONFLOW_API_KEY`、`SUANLI_API_KEY`（可选 `OPENCODE_API_KEY`）。

## 免责

5–10 条 clip 是管线打通 + 方向性信号，**不是统计证明**。规模结论需要
500–2000 句的二期实验。

## 实验结果（三轮，2026-10-06，同 10 clips）

完整数据与结论见 **[docs/findings.md](docs/findings.md)**，生产级裸改指南见
**[docs/naive-llm-guide.md](docs/naive-llm-guide.md)**，原始 JSON 在
`experiments/round{1,2,3}-*/`。一句话版：

| 配置 | 中文 | 英文 | 翻车 |
|---|---|---|---|
| 裸改 suanli v4-flash（护栏前） | **-85%** | -59% | 1/10 单词改错 |
| 裸改 4.1flash | 交卷不稳（2/10 空回复） | 同左 | 空回复（可修） |
| 级联 + v4flash 回填 | **越改越错** ❌ | 有效 ✅ | 恶化 10/40 |
| **级联 + 4.1flash 回填** | **-36%** ✅ | -35% ✅ | **0/40，零过度纠错** |

核心发现：**级联的价值不是省算力，是给强推理模型上笼子**——普通 flash 裸改
最佳、级联拖后腿；4.1flash 反转：级联零翻车、裸改不可靠。中文同音错是纯文本
判别的先天盲区（要声学证据），英文拼写错纯文本可判。smoke 样本量下方差大，
幅度不可信、方向可信（jev 同配置两轮 -33% vs +11%）。

### 生产选型

- 平均效果优先（字幕/笔记）：裸改 v4-flash + 三条护栏（改动量上限/空回复
  重试/输出剥壳），1 次调用 2-3 秒，免费
- 零容忍改错（纪要/存证）：jev-1.13-free 定位 + 4.1flash 约束回填
- 英文场景：级联可直接产品化

## 生产管线（Round 4 冠军方案，可直接部署）

```bash
python -m asr_correct meeting.wav -o out/      # 音频→纠错文本
python -m asr_correct transcript.txt -o out/   # 已有转写→纠错
```

**4.1flash（关思考）两遍流**：裸改 → 验证官复核 → 三重护栏。R4 实测脏句
-62%、零恶化、净句零损伤、p99 < 3s、全程免费额度。默认 ASR 是免费的
SenseVoiceSmall；Round6 的 Qwen3-ASR-1.7B 虽然质量更高，但按 **¥0.000220/秒
输入音频时长**收费，只作为付费实验结果保留，不默认调用。详见
[docs/production-pipeline.md](docs/production-pipeline.md)，工程实现
`asr_correct/`（含 20 个离线单测 + 长音频静音切分 + 兜底链 + 审计报告）。

## Round 6：换 ASR 底座

Round 6 发现：**换免费 ASR 比事后纠错更能提升质量**。免费模型中，
`XingChenAGI/XingChenASR-V3.2` 在同 10 条脏音频上 zh 错误率 0.0383、en 0.0067，
综合错误率 0.0225；原 SenseVoice 为 0.0736。Qwen3-ASR-1.7B 质量更高，但按
¥0.000220/秒音频收费，仅保留为付费实验，不再调用。Diarize 版有时间戳+说话人，
但不适合纯转写质量竞争。完整分析见 [docs/round6-analysis.md](docs/round6-analysis.md)。

## License

MIT
