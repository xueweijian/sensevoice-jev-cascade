# 实验发现全集（三轮，2026-10-06）

同一份考卷：**10 clips**（AISHELL-1 zh ×5 + LibriSpeech test-clean en ×5），
全部经 SenseVoiceSmall 转写并筛查确认**含真实 ASR 错误**（manifest 见
`experiments/round1-ci-v4flash/manifest.smoke.jsonl`）。原始错误率 A=0.0736
（每 100 字错 7.4 个）。错误率 = 对齐后编辑距离 / 参考长度；负数=改善。

原始数据：`experiments/round{1,2,3}-*/results.json`。

## 三轮配置

| 轮次 | 运行位置 | 判别模型 | 回填 LLM |
|---|---|---|---|
| R1 | GitHub Actions（美国 IP） | 仅 jev-1.13-free（硅基流动三款 404，见坑①） | suanli deepseek-v4-flash-0731-free |
| R2 | 本地（中国网络） | Kev-4B / SemIf / diffusiongemma / jev-1.13-free 全通 | suanli deepseek-v4-flash-0731-free |
| R3 | 本地（中国网络） | 同 R2 四款全通 | **opencode deepseek-v4.1-flash**（Go 会员，/zen/go 端点） |

## 总成绩单（错误率变化，负数=好）

### R2 vs R3：同判别模型，只换回填 LLM

| 判别 | R2（普通flash回填） | R3（4.1flash回填） | 恶化句数 R2→R3 |
|---|---|---|---|
| Kev-4B | -14% | **-19%** | 1 → **0** |
| SemIf | +4% ❌ | **-17%** ✅ | 3 → **0** |
| diffusiongemma | +14% ❌ | **-15%** ✅ | 2 → **0** |
| jev-1.13-free | +11% ❌ | **-35%** ✅ 全场最佳 | 4 → **0** |
| 过度纠错总数 | 14 处 | **0 处** | — |

### R3 分语言（最佳组合 jev + 4.1flash）

- zh：0.0779 → 0.0501（-36%）；en：0.0693 → 0.0449（-35%）
- 40 次（4 模型 × 10 句）机会 **零恶化、零过度纠错**

### 裸 LLM 对照（B 组，无门控全文重写）

| LLM | 结果 | 备注 |
|---|---|---|
| suanli v4-flash（非推理） | **-72%**（zh -85% / en -59%），10 句 9 句修到零错 | 1 句真爆雷（0.048→0.143，单词改错） |
| opencode 4.1-flash（推理） | 有效输出零过度纠错，但 **2/10 空回复**（思维链烧光 max_tokens，content 为空） | 需护栏才可用（见技巧文档） |

## 五条硬结论

1. **级联的价值不是省算力，是给强推理模型上笼子。** 普通flash 裸改全场最佳
   （-72%），级联反而拖后腿（R2 三款恶化）；换成 4.1flash 后反转——级联四款
   全部正收益零翻车，裸改却不可靠（空回复）。**模型越强越有主意，越需要
   约束（定位+同音候选+JSON 格式）防跑偏；老实模型直接裸改。**
2. **回填 LLM 的"脾气"决定级联成败**：普通flash 忠实执行判别器的错误定位
   （把噪声放大：自→资、网→望 惨案全是它干的）；4.1flash 会先想"这字真错
   吗"，错的标记拒绝执行（把噪声过滤）。同一判别器（jev）zh 成绩从 +54%
   翻到 -36%，只换了 LLM。
3. **语言结构决定上限**：英文 ASR 错误多为"非词"（proceedcing、
   disistrusting），文本自曝、纯文本可判——三轮里 en 全部正收益（-5%~-46%）；
   中文同音替换产出合法汉字、句子双向通顺，纯文本判别是先天盲区——不加
   声学证据（本地 logits 或双 ASR 分歧）没有出路。
4. **定位精度 P 与级联收益强相关**：R2 里唯一正收益的 Kev-4B det P=0.67
   （标得少但准）；jev P=0.25 / R=0.67（高召回低精度）在"标错就改错"的
   架构里最惨。高召回低精度的判别器适合"只报警不动手"（标黄人工复核）。
5. **Smoke 级数字只能看方向不能看幅度**：jev 级联同一配置 R1 -33% vs R2
   +11%——判别概率在阈值附近抖动被级联放大成完全不同的行为；裸 LLM
   temp0 则逐句完全可复现（R1/R2 的 B 组逐句一致）。级联要稳需定位层
   平滑（多次采样取均值 / 0.4-0.6 缓冲带）。

## 生产选型（大白话）

- **平均效果优先（字幕/转写笔记）**：裸改 suanli `deepseek-v4-flash-0731-free`
  + 护栏（技巧见 `docs/naive-llm-guide.md`），1 次调用 2-3 秒，免费。
- **零容忍改错（纪要/存证）**：jev-1.13-free 定位 + 4.1flash 约束回填，
  慢一点、修得少一点，但架构上不可能大改。
- **英文场景**：任何判别器 + 4.1flash 都可以直接产品化。

## Round 4：纠错技法矩阵（2026-10-06，20 clips = 10 脏 + 10 净，19 条件×模型组合，CI matrix 并发）

数据：`experiments/round4/`（明细 round4.json + manifest）。安全门 = 净句零损伤 +
无大面积删减。**净句（10 句 ASR 全对）是本轮新增维度——前 3 轮从未测过"把对的
改错"，生产上这是最要命的翻车模式。**

### 总表（只列安全门通过的）

| 条件 | 模型 | 脏句错误率 | 改善/恶化 | 净句损伤 | p50/p99 | 调用 |
|---|---|---|---|---|---|---|
| **E3 裸改+验证遍** | **4.1f-不想** | **-62%** | **12/0** | **0句** | **1.3s/2.9s** | 2 |
| E8 jev级联+验证 | 4.1f-不想 | -46% | 15/0 | 0句 | 1.3s/2.6s | 2.5 |
| B0 裸改 | 4.1f-不想 | -47% | 11/1 | 0句 | 1.5s/1.9s | 1 |
| E4 举证式 | 4.1f-不想 | -43% | 9/1 | 0句 | 1.4s/1.8s | 1 |
| E5 few-shot | v4flash | -55% | 10/0 | 0句 | 3.4s/64s | 1 |
| E8 jev级联 | v4flash | -37% | 15/3 | 0句 | 2.6s/88s | 2.5 |

### 六条硬结论（叠加 R1-R3 的五条）

6. **思维链开关是全场最大杠杆**：4.1flash 开想模式裸用全线崩坏（B0：+114% 恶化、
   4 净句损伤、输出被重写到 len_ratio=0）；**关想模式（`reasoning_effort:"none"`）
   全线安全且快 10 倍**。R3 的"推理模型要关笼子"修正为：**想模式必须配约束岗位，
   自由岗位直接关思考**。
7. **冠军 = E3（4.1f关想 × 裸改+验证两遍）**：-62%、12改善/0恶化、净句零损伤、
   p50 1.33s、2 次调用、走 Go 会员免费。验证遍把恶化句 1→0，代价仅 +1 次快调用。
8. **净句损伤暴露了旧结论的盲区**：v4flash 裸改会弄伤 2 句干净句（R1-R3 的
   "-72%"从未测过这个）；**宝玉护栏咒语（E1）反而伤最多**（5句/4字+删减0.82），
   "不要删减内容"不如结构化验证管用。
9. **LLM 自检（E2）不行**：v4flash +85% 恶化——检测幻觉被放大。检测这活留给
   专用判别器或干脆第二遍验证。
10. **few-shot（E5）救了 v4flash**：唯一让它零净损的招（-55%），是 Go 额度耗尽时
    的兜底。
11. **批量 5 句/批（E9）无质量增益且巨慢**——单句粒度定案。

### 生产线终版选型

> **主力：4.1flash（关思考）× 两遍（裸改 → 验证官复核）**，p99 < 3 秒，免费。
> 极致省事：同模型单遍裸改（-47%）。兜底：suanli v4flash + few-shot prompt。
> jev 判别级联正式退役：E8(-46%) 输给 E3(-62%)，还多一次 systemone 调用。

## 踩坑清单（工程向，按伤害排序）

1. **硅基流动 `/v1/systemone` 对海外 IP 返回 404**（ASR 端点
   `/v1/audio/transcriptions` 不受影响）——Kev-4B/SemIf/diffusiongemma 只能
   CN 网络调用；CI 里 probe 失败自动跳过（`run_experiment.py: probe_judges`）。
2. **OpenCode Go 会员推理端点** = `POST https://opencode.ai/zen/go/v1/chat/completions`，
   **必须带 `x-opencode-session` 头**（任意字符串）；普通 `/zen/v1/` 对非
   free 模型报 Insufficient account funds。4.1flash 是推理模型：有
   reasoning_content，max_tokens 要给 3000+，否则思考吃光预算正文为空。
3. **ITN 归一化必须做**：SenseVoice API 输出阿拉伯数字（"9点"）、AISHELL
   标注中文数字（"九点"），不转换会假错字泛滥（`asr_ec.py: norm_zh/
   arabic_int_to_zh`，英文数字词同理 `en_int_to_words`）。
4. **LLM 输出格式三种形态都要兜**：JSON 数组 / 单个对象 / 裸对象逗号串
   `{"i":3,"to":"x"}, {"i":5,...}`——用 `re.findall(r"\{[^{}]*\}")` 兜底。
5. **LibriSpeech test-clean tar 第一个 reader 是 6930**（不是想象中的
   1272）——动态取前两个 reader，别硬编码。
6. **difflib 对齐删除型错误不标 hyp 位置**（ref 多字时 hyp 侧无对应位），
   要补 delete-adjacency 标记（`asr_ec.py: bad_positions`）。
7. **裸改的"爆雷"要验尸**：R3 的 B 组 2 句错误率=1.0，查原始返回全是空串
   （推理模型没交卷），不是过度纠错。按"空回复重试"修，别按"模型爱乱改"修。
8. **后台进程要杀干净**：本地多次启动 run_experiment 会并跑互踩（限流
   400、结果文件互相覆盖）。启动前 `ps | grep run_experiment` 检查。
9. SemIf 偶发 systemone HTTP 400 `code 20015`（参数校验），疑与特定
   state/questions 组合有关，**待查**。

## 复现

```
# CI（海外，三款硅基流动判别会自动跳过）：
#   push 到 main 或手动 workflow_dispatch，见 .github/workflows/smoke.yml
# 本地（CN，四款全通）：
python scripts/prep_data.py --work /tmp/work
python scripts/screen.py --work /tmp/work --need 5
python scripts/run_experiment.py --manifest /tmp/work/manifest.smoke.jsonl \
  --pinyin-index /tmp/work/pinyin_index.json --out results
# 换 4.1flash 回填：环境变量 LLM_PROVIDER=opencode
```

注意：smoke 的 10 句样本量下幅度不可靠（见结论 5），扩到 500-2000 句
才能出统计可信的数字（二期）。
