# Round 4 过程记录（2026-10-06）

本文记录第四轮实验的**完整过程**：材料研究 → 设计决策 → 实施迭代（含三次翻车
与修复）→ 结果。原始数据在 `experiments/round4/`（19 组逐句明细在 `records/`）。

## 一、用户提供的四份材料与拆解

| 来源 | 核心技法 | 针对的病 |
|---|---|---|
| 宝玉《音频转文本方案》[baoyu.io](https://baoyu.io/blog/audio-to-text-transcription-solution) | "纠正错别字、去掉口癖、**不要删减内容**" 护栏咒语 + 分块 continue | LLM 偷懒删内容 |
| daymade/transcript-fixer skill（claude-code-skills 仓库） | ①修正必须举证（解释是哪类 ASR 错误）②不确定挂起不改（"看得见的乱码好过流畅的错猜"）③词典沉淀复用 ④永不润色改写 | 幻觉乱改 |
| RLLM-CF（arxiv 2505.24347，HUST/SJTU/AISpeech） | 三阶段：错误预检测 → CoT 子任务迭代修 → **答案验证回滚**。AISHELL-1 -21% / LibriSpeech -11.4%（GPT-4o，零训练） | 幻觉乱改 |
| ASR-EC Benchmark（EMNLP 2025 Industry） | zero-shot 提示词 CER 27-34% vs LoRA 7-12%——脏真实语音上提示词有天花板，微调碾压 | 提示词上限 |

交叉洞察：
1. RLLM-CF 的第一阶段就是本项目最初"Jev 判断要不要改"的学术版——它让 LLM 自检。
   Round 4 的 E2 直接测了这条路（结论：死路，见后）。
2. ASR-EC 的"提示词不行"与本仓 R1-R3 的"裸改 -72%"不矛盾：前者是高 CER 脏真实
   语音，后者是干净读稿。音频越真实，提示词路线越接近天花板，LoRA 是二期备胎。
3. transcript-fixer 的"举证/挂起"与 RLLM-CF 的"验证回滚"本质同源：**给 LLM 的
   输出加一道否决权**。Round 4 验证遍（E3）正是它的最简形态。

## 二、实验设计的关键决策

1. **测试集升级为 20 句 = 10 脏 + 10 净**。前三轮只有脏句，天然偏爱激进纠错；
   "把对的改错"（净句损伤）从未被测过——而这是生产上最要命的翻车模式。
2. **安全门先行**：净句零损伤 + 无大面积删减（len_ratio ≥ 0.75；0.95 会误伤
   "删掉多余错字"的合法修复）→ 过门者才比质量与速度。
3. **模型三档**：v4flash（suanli 免费非推理）/ **4.1f-不想**（opencode Go，
   `reasoning_effort:"none"`，实测 0 reasoning token）/ 4.1f-想（默认思维链）。
   关思考参数由用户提示，探测确认：`thinking:false`、`enable_thinking:false`、
   `chat_template_kwargs`、`reasoning:{type:none}` 四种形态都关不掉（仍输出
   30+ reasoning token），只有 `reasoning_effort:"none"` 干净关死（0 token）。
4. **单仓库 matrix 并发**（无需多仓库）：1 prep + 19 条件 job + 1 聚合，
   GitHub 公共仓库 20 并发额度内；job 内 2 路线程并发 + 随机 0-20s 错峰起步。
5. **重复次数**：判别/想模式条件 ×3（方差教训），纯提示词条件 ×2。

## 三、实施迭代（三次翻车实录）

1. **YAML 多行内联 python 炸 workflow**（run 37435283150 之前那发，0 job 直接
   failure）：`run: python -c "` 的续行顶格写，YAML 解析死。修复：内联逻辑并进
   prep_round4.py（--pinyin-out 参数）。
2. **输出目录没建**（run 37435283150，14/19 job 挂）：19 个条件把 API 全调完，
   最后写 `r4/*.json` 时 FileNotFoundError——白烧一轮调用。修复：写文件前
   `os.makedirs(dirname, exist_ok=True)`。
3. **聚合两个连环坑**（run 37436264999，19 job 全绿但 aggregate 失败）：
   a) download-artifact 的 pattern `r4-*` 把 `r4-manifest` 也捞进来，其中的
      `pinyin_index.json` 没有 `condition` 键 → KeyError。修复：agg 对非条件
      文件 isinstance 防御跳过。
   b) persist 步骤"无 commit 也 force push"，把 results 分支重置成了 main——
      分支事故。修复：`git fetch origin results` 基于远端建分支 + 只有真有
      commit 才 push。数据无损（R1-R4 全档都在 main 的 experiments/）。
   聚合后来在本地完成（产物全在 artifacts），并重建了 results 分支。

## 四、结果与六条硬结论

总表见 `experiments/round4/round4-summary.md`。冠军 **E3 = 4.1f-不想 × 两遍
（裸改→验证官复核）**：脏句 -62%、12 改善/0 恶化、净句零损伤、p50 1.33s/
p99 2.87s、2 次调用/句、Go 会员免费。

1. **思维链开关是全场最大杠杆**：4.1f 想模式裸用全线崩坏（B0 +114%、4 净句
   损伤、len_ratio=0 式重写）；关想全线安全且快 10 倍。R3 的"推理模型要关笼子"
   修正为：想模式必须配约束岗位（级联回填那种），自由岗位直接关想。
2. 验证遍（E3）把恶化句 1→0、净损 2 句→0，代价仅 +1 次快调用。
3. 宝玉咒语护不住净句（E1：5 句损伤 + 删减 0.82）——喊话不如结构化复核。
4. LLM 自检（E2/RLLM-CF 阶段1）死路：v4flash +85% 恶化，检测幻觉被放大。
5. few-shot（E5）是 v4flash 唯一零净损形态（-55%）——兜底位。
6. 批量 5 句/批（E9）无质量增益且 p50 77s——单句粒度定案。

## 五、与 R1-R3 的关系

- R1（CI，仅 jev 通）：级联 -33%，方差未识。
- R2（本地四判别 + v4flash 回填）：级联恶化，定位精度 P 决定成败。
- R3（本地四判别 + 4.1f-想回填）：级联反超（-35%，零翻车）——"笼子"结论。
- R4（技法矩阵 + 净句考卷）：关想 + 验证遍 = 又快又稳的最优解（-62%），级联
  与想模式一起退役到特定场景（约束岗位/零容忍改错）。

## 六、遗留

- SemIf 偶发 systemone 400 code 20015（参数校验）仍未查（R2 遗留）。
- 读稿语料测不了"去口癖"——需要业务口语音频（生产试点任务）。
- 500-2000 句二期（统计可信 + LoRA 对照）未启动。
