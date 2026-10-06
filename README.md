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

## License

MIT
