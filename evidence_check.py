# -*- coding: utf-8 -*-
"""
证据校验：逐项重算 EVIDENCE.md 里的数字
======================================================
第三方复核需要「原始文件 + 重算路径」。本脚本就是那条重算路径。
用法：python evidence_check.py
"""
import re, sys, subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NL = chr(10)
OK, FAIL = "[OK]", "[FAIL]"
_fails = []


def check(label, got, want, tol=0):
    good = (abs(got - want) <= tol) if isinstance(want, (int, float)) else (got == want)
    print(f"  {OK if good else FAIL} {label}: 实算 {got} / 文中 {want}")
    if not good:
        _fails.append(label)
    return good


def ts(s):
    return datetime.strptime("2026-10-09 " + s, "%Y-%m-%d %H:%M:%S")


print("=" * 60)
print("① 并行吞吐（源：logs/sampler.log）")
log = (ROOT / "logs" / "sampler.log").read_text(encoding="utf-8")
lines = [(m.group(1), m.group(2)) for m in
         (re.match(r"\[(\d\d:\d\d:\d\d)\] (.*)", l) for l in log.split(NL)) if m]


def batch_rate(marker):
    """从「页面池就绪」标记回溯最近的 CDP 就绪行，再向后找第一条「完成：N/N 成功」"""
    for i, (t, txt) in enumerate(lines):
        if marker in txt:
            t0 = next((lines[j][0] for j in range(i, -1, -1)
                       if "CDP 9222 就绪" in lines[j][1]), None)
            if t0 is None:
                return None
            for j in range(i, min(i + 60, len(lines))):
                mm = re.search(r"完成：(\d+)/\1 成功", lines[j][1])
                if mm:
                    n = int(mm.group(1))
                    secs = (ts(lines[j][0]) - ts(t0)).total_seconds()
                    return t0, lines[j][0], n, secs, n / secs * 3600
    return None


for marker, want in [("页面池就绪：3 个标签页（并行度 3，已开焦点模拟", 275),
                     ("页面池就绪：5 个标签页（并行度 5，已开焦点模拟", 409)]:
    r = batch_rate(marker)
    if r:
        t0, t1, n, secs, rate = r
        print(f"  {marker[4:12]}: {t0} → {t1} = {secs:.0f}s, {n} 条")
        check("吞吐", round(rate), want, tol=2)
    else:
        print(f"  {FAIL} 批次未匹配: {marker[:20]}")

print(NL + "①b 吞吐批次的题型（必须声明，否则高估生产吞吐）")
import json as _json
for f, label in [("data/test_parallel.jsonl", "3 标签页"), ("data/test_p5.jsonl", "5 标签页")]:
    rows = [_json.loads(l) for l in (ROOT / f).read_text(encoding="utf-8").split(NL) if l.strip()]
    ids = sorted({r["prompt_id"] for r in rows})
    trig = sum(1 for r in rows if r.get("search_triggered"))
    cites = sum(len(r.get("citations") or []) for r in rows)
    print(f"  {label}: 题={ids} 触发检索={trig}/{len(rows)} 引用合计={cites}")
    check(f"{label} 题型=仅I01（无检索题）", ids == ["I01"] and trig == 0, True)

print(NL + "② U+2028（源：data/samples.jsonl.bak 规范化前）")
bak = ROOT / "data" / "samples.jsonl.bak"
cur = ROOT / "data" / "samples.jsonl"
if bak.exists():
    t = bak.read_text(encoding="utf-8")
    u = t.count(chr(0x2028)) + t.count(chr(0x2029))
    check("规范化前 U+2028/2029 个数", u, 16)
    check("规范化前 splitlines() 段数", len(t.splitlines()), 256)
    check("规范化前真行数", len([x for x in t.split(NL) if x.strip()]), 240)
else:
    print(f"  {FAIL} 缺 {bak.name}")
t2 = cur.read_text(encoding="utf-8")
check("规范化后 U+2028 字面量", t2.count(chr(0x2028)) + t2.count(chr(0x2029)), 0)
check("规范化后两种读法一致",
      len(t2.splitlines()) == len([x for x in t2.split(NL) if x.strip()]), True)

print(NL + "③ splitlines 读取点残留（应为 0）")
hits = subprocess.run(
    ["grep", "-rn", 'read_text(encoding="utf-8").splitlines()', "--include=*.py", "."],
    cwd=str(ROOT), capture_output=True, text=True).stdout.strip()
check("残留数", len([x for x in hits.split(NL) if x.strip()]), 0)

print(NL + "④ Ctrl+Shift+K（源：data/raw/reliability_probe.log）")
rp = ROOT / "data" / "raw" / "reliability_probe.log"
if rp.exists():
    c = rp.read_text(encoding="utf-8")
    check("「回答容器数=0」出现次数", c.count("回答容器数=0"), 3)
    check("含方式 B 标题", "方式 B：Ctrl+Shift+K 新对话" in c, True)
else:
    print(f"  {FAIL} 缺 reliability_probe.log")

print(NL + "⑤ 语法（report2/report.py/verify_audit 等）")
bad = []
for f in ["report2.py", "report.py", "verify_audit.py", "analyze_final.py",
          "permutation_test.py", "geolib.py", "sampler/run_samples.py"]:
    p = ROOT / f
    if not p.exists():
        continue
    r = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        bad.append(f)
print(f"  {OK if not bad else FAIL} 编译失败: {bad if bad else '无'}")
if bad:
    _fails.append("py_compile")

print(NL + "=" * 60)
if _fails:
    print(f"{FAIL} 未通过 {len(_fails)} 项: {_fails}")
    sys.exit(1)
print(f"{OK} 全部通过")
