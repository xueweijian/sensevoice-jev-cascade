#!/usr/bin/env python3
"""Round 4 aggregate: merge per-condition outputs -> summary table + JSON."""
import glob
import json
import os

BASELINES = [
    ("A 原始ASR（R1-3 基线）", "0.0736 → 0.0736 (0%)", "—", "未测", "未测", "—", "—", "—"),
    ("B0 裸改 v4flash（R1-3）", "0.0736 → 0.0202 (-72%)", "9/1", "未测", "未测", "❓", "≈2-3s", "1"),
    ("D 级联 jev+4.1flash想（R3）", "0.0736 → 0.0475 (-35%)", "5/1", "未测", "未测", "❓", "≈11s", "3+"),
]
MODEL_LABEL = {"v4flash": "v4flash", "d41": "4.1f-不想", "d41think": "4.1f-想"}


def main():
    rows = []
    for p in sorted(glob.glob("r4/*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print("skip", p, e)
            continue
        rows.append((d["condition"], d["model"], d["summary"], d.get("wall_min")))
    rows.sort(key=lambda x: (x[0], x[1]))

    lines = ["# Round 4 纠错技法矩阵 — 结果汇总", "",
             "测试集：20 clips = 10 脏（真实ASR错误，R1-R3 同款）+ 10 净（ASR 全对）。",
             "安全门：净句零损伤 + 无大面积删减（len_ratio ≥ 0.75，单字级合法删改放行）。`safe=❌` 不能上生产线。", "",
             "| 条件 | 模型 | 脏句错误率（前→后） | 改善/恶化句 | 净句损伤 | 删减下限 | 安全 | p50/p99延迟 | 调用/句 |",
             "|---|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(b) + " |" for b in BASELINES]
    for cond, model, s, wall in rows:
        de, de_b = s.get("dirty_err_after"), s.get("dirty_err_before")
        if de is None or not de_b:
            lines.append(f"| {cond} | {MODEL_LABEL.get(model, model)} | "
                         f"FAIL(err={s.get('n_err')}) | — | — | — | ❓ | — | — |")
            continue
        delta = (de - de_b) / de_b * 100
        lines.append(
            f"| {cond} | {MODEL_LABEL.get(model, model)} "
            f"| {de_b:.4f} → {de:.4f} ({delta:+.0f}%) "
            f"| {s['dirty_improved']}/{s['dirty_worsened']} "
            f"| {s['clean_damaged']}句/{s['clean_changed_chars']}字 "
            f"| {s['min_len_ratio']} "
            f"| {'✅' if s['safe'] else '❌'} "
            f"| {s['lat_p50']}s/{s['lat_p99']}s "
            f"| {s['calls_mean']} |")
    lines += ["", f"共 {len(rows)} 个条件×模型组合，明细 JSON 在同目录 round4.json。", ""]

    os.makedirs("results", exist_ok=True)
    with open("results/round4-summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open("results/round4.json", "w", encoding="utf-8") as f:
        json.dump({"files": sorted(os.path.basename(p) for p in glob.glob("r4/*.json")),
                   "rows": [{"condition": c, "model": m, "summary": s, "wall_min": w}
                            for c, m, s, w in rows]}, f, ensure_ascii=False, indent=1)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
