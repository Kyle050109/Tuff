# -*- coding: utf-8 -*-
"""
ds_analyze.py · DeepSeek Search API 来源层分析（2026-10-20 新建，补齐「数字由程序产出」缺口）
======================================================
回答：DeepSeek 搜索层对某类目返回了什么、本品牌/竞品各占多少、来自哪些域名、每个品牌覆盖了多少 query。

口径（全部显式写在这里）：
  · 匹配字段  = title + " " + snippet（不区分大小写）
      依据：此口径逐位复现 2026-10-10 双引擎交叉报告的本品牌数（松胜 222 / 水裹 261）。
  · 引用分类  = 本品牌优先：含本品牌 → own；否则含任一竞品 → comp；否则 neutral（互斥）
  · 竞品表    = 题库 meta.competitors（不再手写）。--exclude 可剔除别名（用于复现历史口径）
  · 品牌覆盖  = 该 query 的结果里至少一条命中该品牌（analysis_brands 别名）
  · 域名      = URL host 去 www.；引用条目口径（同 URL 重复出现计多次），另报去重 URL 数
  · 注意：这是 Search API（来源层），不是 DeepSeek 对话答案（陈述层）。按方法论 §二 只作内部排查，不与豆包同表。

用法：
  python ds_analyze.py --prompts prompts/anmo_chair_v1.json --data data/deepseek/ds_chair_baseline.jsonl --json-out out/ds_chair.json
  # 复现 10-10 报告历史口径：
  python ds_analyze.py --prompts prompts/shenzhen_spa_v1.json --data data/deepseek/ds_spa_baseline.jsonl --exclude TENZ
"""
import argparse, json, sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


def read_jsonl(p):
    out = []
    for line in Path(p).read_text(encoding="utf-8").split("\n"):
        if line.strip():
            out.append(json.loads(line))
    return out


def host(u):
    try:
        h = urlparse(u).netloc.lower()
    except Exception:
        return "?"
    return h[4:] if h.startswith("www.") else (h or "?")


def blob(r):
    return ((r.get("title") or "") + " " + (r.get("snippet") or "")).lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--exclude", default="", help="逗号分隔：从竞品表剔除的别名（仅用于复现历史口径）")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()

    meta = json.loads(Path(a.prompts).read_text(encoding="utf-8")).get("meta") or {}
    own = [str(x) for x in meta["own_brand"]]
    excl = {x.strip().lower() for x in a.exclude.split(",") if x.strip()}
    comps = [str(c) for c in meta["competitors"] if str(c).lower() not in excl]
    brands = {str(k): [str(x) for x in v] for k, v in (meta.get("analysis_brands") or {}).items()}
    brands = {"★" + own[0]: own, **brands}

    Q = read_jsonl(a.data)
    assert Q, "数据为空"
    R = [(q["query"], r) for q in Q for r in (q.get("results") or [])]
    assert R, "无搜索结果"
    N = {"queries": len(Q), "results": len(R), "unique_urls": len({r.get("url") for _, r in R}),
         "own_brand": own, "competitors_used": comps, "excluded": sorted(excl)}

    # ── 1. 引用分类 ──
    cls = Counter()
    by_cls_host = defaultdict(Counter)
    for _, r in R:
        b = blob(r)
        k = "own" if any(o.lower() in b for o in own) else ("comp" if any(c.lower() in b for c in comps) else "neutral")
        cls[k] += 1
        by_cls_host[k][host(r.get("url") or "")] += 1
    N.update({f"n_{k}": cls[k] for k in ("own", "comp", "neutral")})
    N["own_share_pct"] = 100 * cls["own"] / len(R)

    print("=" * 60)
    print(f"[口径] {Path(a.prompts).name} · own={own} · 竞品 {len(comps)} 项" + (f"（剔除 {sorted(excl)}）" if excl else ""))
    print(f"【1】总览  query {len(Q)} · 引用 {len(R)} · 去重 URL {N['unique_urls']}")
    print(f"  含本品牌 {cls['own']} · 含竞品 {cls['comp']} · 中性 {cls['neutral']}")
    print(f"  本品牌占引用比 {N['own_share_pct']:.1f}%")

    # ── 2. 域名结构 ──
    hc = Counter(host(r.get("url") or "") for _, r in R)
    N["top_hosts"] = hc.most_common(a.top)
    print(f"\n【2】引用域名 Top {a.top}（引用条目口径）")
    for h, n in hc.most_common(a.top):
        print(f"  {h:<28}{n:>5}  {100*n/len(R):5.1f}%")
    N["top_hosts_own"] = by_cls_host["own"].most_common(a.top)
    print(f"\n  ↳ 含本品牌引用的来源域名 Top {a.top}")
    for h, n in by_cls_host["own"].most_common(a.top):
        print(f"    {h:<26}{n:>5}")
    dy = sum(n for h, n in hc.items() if "douyin" in h)
    N["douyin_share_pct"] = 100 * dy / len(R)
    print(f"  抖音域名合计 {dy}（{N['douyin_share_pct']:.1f}%）")

    # ── 3. 品牌 query 覆盖 ──
    uq = sorted({q["query"] for q in Q})
    N["unique_queries"] = len(uq)
    if len(uq) != len(Q):
        print(f"\n  ⚠ query 有重复：{len(Q)} 行 / {len(uq)} 个不同 query——覆盖率分母用不同 query 数")
    print(f"\n【3】品牌 query 覆盖（该 query 结果中 ≥1 条命中，分母 {len(uq)}）· 命中引用条数 · 命中去重 URL")
    cov = {}
    for bn, al in brands.items():
        al_l = [x.lower() for x in al]
        qs, cites, urls = set(), 0, set()
        for q, r in R:
            if any(x in blob(r) for x in al_l):
                qs.add(q); cites += 1; urls.add(r.get("url"))
        cov[bn] = {"queries": len(qs), "cov_pct": 100 * len(qs) / len(uq), "cites": cites, "urls": len(urls)}
    for bn, v in sorted(cov.items(), key=lambda kv: -kv[1]["queries"]):
        print(f"  {bn:<10} {v['queries']:>4}/{len(uq)} = {v['cov_pct']:5.1f}%   引用 {v['cites']:>4}   URL {v['urls']:>4}")
    N["brand_coverage"] = cov

    # ── 4. 本品牌缺席 query（长尾候选，算法 15 的来源层版本） ──
    own_l = [o.lower() for o in own]
    hitq = {q for q, r in R if any(o in blob(r) for o in own_l)}
    miss = [q for q in uq if q not in hitq]
    N["own_missing_queries"] = miss
    print(f"\n【4】本品牌缺席 query {len(miss)}/{len(uq)}（样例前 10）")
    for q in miss[:10]:
        print(f"  · {q}")

    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(N, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写出 {a.json_out}")


if __name__ == "__main__":
    main()
