# Round 7：全部免费 ASR × 冠军纠错

Qwen3-ASR-1.7B 已明确收费，本轮完全不调用。所有模型使用同一 20 条考卷；每个 ASR 只调用一次/音频，之后统一接 4.1flash 关思考两遍流，CSC 门控关闭。

## 总体：原始 ASR → 冠军纠错后

| 免费 ASR | 原始错误率 | 纠错后 | 变化（负数=变好） | 改善/持平/恶化 |
|---|---:|---:|---:|---:|
| sensevoice | 0.034 | 0.0149 | -56.2% | 9/31/0 |
| xingchen-v32 | 0.0112 | 0.0134 | 19.6% | 1/37/2 |
| xingchen-ultra | 0.0142 | 0.0134 | -5.6% | 1/39/0 |
| xingchen-diarize | 0.0843 | 0.0914 | 8.4% | 2/34/4 |

## 按来源分组

`source_dirty` = 原 SenseVoice 筛出的 10 条脏音频；`source_clean` = 原 SenseVoice 筛出的 10 条净音频。换 ASR 后，净音频不保证对新 ASR 仍然完全正确，所以同时报告原始错误率。

| ASR | 组 | 原始 | 纠错后 | 变化 | 改善/持平/恶化 | 纠错后非零句 |
|---|---|---:|---:|---:|---:|---:|
| sensevoice | dirty | 0.068 | 0.0298 | -56.2% | 9/11/0 | - |
| sensevoice | clean | 0.0 | 0.0 | 0.0% | 0/20/0 | 20 |
| xingchen-v32 | dirty | 0.0225 | 0.0267 | 18.7% | 1/17/2 | - |
| xingchen-v32 | clean | 0.0 | 0.0 | 0.0% | 0/20/0 | 20 |
| xingchen-ultra | dirty | 0.0284 | 0.0267 | -6.0% | 1/19/0 | - |
| xingchen-ultra | clean | 0.0 | 0.0 | 0.0% | 0/20/0 | 20 |
| xingchen-diarize | dirty | 0.0534 | 0.07 | 31.1% | 0/16/4 | - |
| xingchen-diarize | clean | 0.1152 | 0.1128 | -2.1% | 2/18/0 | 20 |

## 时间戳/说话人

Diarize 的纠错输入使用 segments.text 去掉 speaker 标签；原始 segments 和 speakers 仍保存在 round7.json。
- sensevoice: timestamps=no, speakers=none
- xingchen-v32: timestamps=no, speakers=none
- xingchen-ultra: timestamps=no, speakers=none
- xingchen-diarize: timestamps=yes, speakers=['1', '2', '3']
