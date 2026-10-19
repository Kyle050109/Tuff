# -*- coding: utf-8 -*-
"""
geo-lab 公共模块
统一 JSONL 读写纪律 —— 解决 U+2028 / U+2029 假换行问题
"""
import json
from pathlib import Path

_ESCAPES = {"\u2028": "\\u2028", "\u2029": "\\u2029"}


def jdumps(obj):
    """写 JSONL 用。必须转义 U+2028/U+2029。

    它们是**合法 JSON 字符、无需转义**，但 Python 的 `str.splitlines()` 会把它们当换行，
    导致下游按行读取时把一条记录切成多条、`json.loads` 失败、**被静默丢弃**。
    （实测：抖音视频标题带入 16 个 U+2028，240 行文件被 splitlines() 切成 256 段、丢 4 条有效样本。）
    """
    s = json.dumps(obj, ensure_ascii=False)
    for k, v in _ESCAPES.items():
        s = s.replace(k, v)
    return s


def read_jsonl(path, on_bad="raise"):
    """读 JSONL。**只按 '\\n' 切，永不用 splitlines()**。

    on_bad: 'raise'（默认，解析失败立即报错）| 'collect'（返回坏行清单）
    返回 list[dict]；on_bad='collect' 时返回 (rows, bad)
    """
    txt = Path(path).read_text(encoding="utf-8")
    rows, bad = [], []
    for i, line in enumerate(txt.split("\n"), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as e:
            if on_bad == "raise":
                raise ValueError(
                    f"{path}: 第 {i} 行 JSON 解析失败（{e}）。"
                    f"按行解析 JSONL 失败通常是编码/转义问题，不要静默跳过——可疑内容：{line[:120]!r}"
                ) from e
            bad.append((i, str(e)[:80], line[:120]))
    if on_bad == "collect":
        return rows, bad
    return rows


def dedupe_last(rows, key=None, only_ok=True):
    """按 key 去重，保留最后一条（重试语义：后跑的覆盖先跑的失败）。

    key 默认自动判定：**只要记录里出现 account 字段就纳入去重键**——
    否则多账号文件会把同一 (prompt_id, run_idx) 下不同账号的记录折叠成一条（实测把 75 条折成 33 条）。
    """
    if key is None:
        has_acc = any(r.get("account") for r in rows)
        key = ("prompt_id", "run_idx", "account") if has_acc else ("prompt_id", "run_idx")
    latest = {}
    for r in rows:
        latest[tuple(r.get(k) for k in key)] = r
    out = list(latest.values())
    if only_ok:
        out = [r for r in out if r.get("ok")]
    return out


def normalize_file(path, backup=True):
    """就地规范化已有的脏 JSONL：读正确路径 → 用 jdumps 重写（转义 U+2028/2029）。"""
    p = Path(path)
    rows, bad = read_jsonl(p, on_bad="collect")
    if backup:
        bak = p.with_suffix(p.suffix + ".bak")
        if not bak.exists():
            bak.write_bytes(p.read_bytes())
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(jdumps(r) + "\n")
    # 校验
    txt = p.read_text(encoding="utf-8")
    return {
        "file": str(p),
        "records": len(rows),
        "bad_before": len(bad),
        "u2028_after": txt.count("\u2028") + txt.count("\u2029"),
        "lines_splitlines": len(txt.splitlines()),
        "lines_by_nl": len([x for x in txt.split("\n") if x.strip()]),
    }


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        print(normalize_file(f))
