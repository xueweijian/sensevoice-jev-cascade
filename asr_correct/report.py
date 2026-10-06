"""Output rendering: corrected text, JSON report, human diff view."""
import json


def write_outputs(result, outdir, json_path=None, quiet=False):
    """Write corrected.txt / report.json / diff.md into outdir."""
    import os
    os.makedirs(outdir, exist_ok=True)
    txt_path = os.path.join(outdir, "corrected.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(result["corrected_text"] + "\n")

    report = {
        "audio": result.get("audio"),
        "asr": result.get("asr"),
        "stats": result["stats"],
        "config": {k: v for k, v in result["config"].items()},
        "sentences": [
            {"i": i, "orig": s["orig"], "final": s["final"],
             "edits": s.get("edits", []), "guards": s.get("guards", []),
             "models": s.get("models", []), "calls": s.get("calls", 0)}
            for i, s in enumerate(result["sentences"])],
    }
    jp = json_path or os.path.join(outdir, "report.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    with open(os.path.join(outdir, "diff.md"), "w", encoding="utf-8") as f:
        f.write(render_diff(result))
    if not quiet:
        print(f"[out] {txt_path}\n[out] {jp}\n[out] {os.path.join(outdir, 'diff.md')}")
    return {"text": txt_path, "json": jp}


def render_diff(result):
    lines = ["# 校对对照", ""]
    for i, s in enumerate(result["sentences"]):
        if s["orig"] == s["final"] and not s.get("guards"):
            continue
        lines.append(f"## 句 {i}")
        lines.append(f"- 原：{s['orig']}")
        lines.append(f"- 改：{s['final']}")
        if s.get("edits"):
            lines.append("- 变更：" + "，".join(
                f"{p}`{a or '∅'}`→`{b or '∅'}`" for p, a, b in s["edits"]))
        if s.get("guards"):
            lines.append("- 护栏：" + "；".join(s["guards"]))
        lines.append("")
    return "\n".join(lines) if len(lines) > 2 else "# 校对对照\n\n（无改动）\n"
