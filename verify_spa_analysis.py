# -*- coding: utf-8 -*-
"""
verify_spa_analysis.py · 水裹+ 反向工程报告的完整复算脚本
（五轮审核 N5/N7 修复：替换空 stub，使报告全部数字可独立复现）
运行：cd geo-lab && python verify_spa_analysis.py
"""
import json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = ROOT / "data" / "spa_samples.jsonl"
if not data.exists():
    print(f"[ERROR] 数据文件不存在: {data}")
    sys.exit(1)

rows = [json.loads(l) for l in data.read_text(encoding="utf-8").splitlines() if l.strip()]
dd = {}
for r in rows: dd[(r["prompt_id"], r["run_idx"])] = r
valid = [r for r in dd.values() if r.get("ok")]

COMP = ["汤悦","HEATJOY","heatjoy","汤崎","TENZ","阿奇拉","熹汤","大江户","极乐汤","泉之源"]
OWN = ["水裹"]
disc = [r for r in valid if not any(b in r["text"] for b in OWN)]

# ============================================
# §一 渠道版图（去重键 = (title, url) 对）
# ============================================
print("=" * 60)
print("§一 渠道版图（去重键 = (title, url)）")
hits = set()
for r in disc:
    for c in (r.get("citations") or []):
        if "水裹" in ((c.get("title") or "") + (c.get("url") or "")):
            hits.add((c.get("url"), c.get("title")))
doms = Counter()
for u, t in hits:
    d = u.split("/")[2].replace("www.", "") if u and u.startswith("http") else "?"
    doms[d] += 1
for d, n in doms.most_common(10):
    print(f"  {d}: {n}")
print(f"  合计 {len(hits)} 条去重命中")

# ============================================
# §六 渠道条件提及率（含渠道 vs 补集，五轮审核 N11 修正）
# ============================================
print("\n§六 渠道条件提及率（补集对照，N11 修正版）")
chans = {"象上汇官网": ["xshhotels"], "携程": ["ctrip"], "KKday/Klook": ["kkday", "klook"],
         "新浪": ["sina.cn"], "抖音": ["douyin"], "地方媒体(gdzjdaily)": ["gdzjdaily"]}
for name, dl in chans.items():
    hit = [r for r in disc if any(any(d in (c.get("url") or "") for d in dl) for c in (r.get("citations") or []))]
    miss = [r for r in disc if r not in hit]
    h_m = sum(1 for r in hit if "水裹" in (r.get("answer") or ""))
    m_m = sum(1 for r in miss if "水裹" in (r.get("answer") or "")) if miss else 0
    h_r = 100 * h_m / len(hit) if hit else 0
    if miss:
        m_r = 100 * m_m / len(miss)
        print(f"  {name}: 含{len(hit)}({h_r:.1f}%) vs 补集{len(miss)}({m_r:.1f}%) → 差{h_r - m_r:+.1f}pp")
    else:
        print(f"  {name}: 含{len(hit)}({h_r:.1f}%) vs 补集0(N/A) → 全覆盖，不可估计边际效应")

# ============================================
# §二 句级绑定率（两种切分口径，五轮审核 N13 修正）
# ============================================
print("\n§二 句级绑定率（双口径 + 敏感性标注）")
HOOKS = ["自助", "海鲜", "水果", "过夜"]
BRANDS = ["水裹", "汤悦", "阿奇拉"]

def sent_bind(brand, hook, use_comma=False):
    ment = [r for r in disc if brand in (r.get("answer") or "")]
    if not ment: return 0, 0
    seps = "[。！？\n" + ("，," if use_comma else "") + "]"
    bind = 0
    for r in ment:
        ans = r.get("answer") or ""
        found = False
        for m in re.finditer(re.escape(brand), ans):
            starts = [x.end() for x in re.finditer(seps + "|(?:\d[.、])", ans[:m.start()])]
            s = max(starts) if starts else 0
            ends = [x.start() for x in re.finditer(seps, ans[m.start():])]
            e = m.start() + min(ends) if ends else len(ans)
            if hook in ans[s:e]:
                found = True; break
        if found: bind += 1
    return bind, len(ment)

print(f"  {'品牌·卖点':<12} {'句末切分':>8} {'+逗号':>8} {'敏感性':>8}")
for b in BRANDS:
    for h in HOOKS:
        b1, n = sent_bind(b, h, False)
        b2, _ = sent_bind(b, h, True)
        if n == 0: continue
        r1, r2 = 100 * b1 / n, 100 * b2 / n
        print(f"  {b}·{h:<8} {r1:>6.1f}% {r2:>6.1f}%  ±{abs(r1 - r2):.1f}pp")

print("\n⚠ 句级绑定率对切分规则敏感（上表 ±列）；跨品牌比较须用同一口径；")
print("  验收阈值应报双口径区间而非单值（五轮审核 N13）。")

# ============================================
# 引用结构对照（去重键声明）
# ============================================
print("\n引用结构对照（去重键 = (title, url)，N12 修正）")
for brand in ["水裹", "阿奇拉"]:
    p = re.compile(brand)
    pairs = set()
    for r in disc:
        for c in (r.get("citations") or []):
            if p.search((c.get("title") or "") + (c.get("url") or "")):
                u = c.get("url") or ""
                pairs.add((u, c.get("title") or ""))
    dy = sum(1 for u, t in pairs if "douyin" in u)
    ct = sum(1 for u, t in pairs if "ctrip" in u)
    ot = sum(1 for u, t in pairs if "kkday" in u or "klook" in u)
    print(f"  {brand}: {len(pairs)}条 | 抖音{dy}({100*dy/max(len(pairs),1):.0f}%) 携程{ct} OTA{ot}")

print("\n[OK] 全部复算完成（脚本 md5 可供核对表钉扎）")
import hashlib
print(f"本脚本 md5: {hashlib.md5(Path(__file__).read_bytes()).hexdigest()[:8]}")
