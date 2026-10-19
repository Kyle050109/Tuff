# -*- coding: utf-8 -*-
"""
DS GeoScout · DeepSeek Search API 的 GEO 监测采集器
======================================================
用途：用 DeepSeek Search API 直接探测 AI 搜索引擎为指定类目/品牌
     返回了哪些引用内容——比豆包的浏览器采集更快、更便宜、更透明。

用法：
  python ds_geoscout.py --prompts prompts/anmo_chair_v1.json --out data/ds_chair_baseline.jsonl
  python ds_geoscout.py --queries "按摩椅推荐,按摩椅哪个牌子好" --out data/ds_quick_test.jsonl

成本：0.005 元/次（100 题×2 遍 = 200 次 = 1 元）
限速：5 QPS（自动限速）

输出字段（比豆包多出的关键信息用 ★ 标注）：
  query          搜索词
  results        搜索结果列表
    ├ title         页面标题
    ├ url           页面 URL
    ├ snippet       短摘要（~100-200 字符）
    ├ summary       长摘要（~600-800 字符）
    ├ ★rerank_score 排序分 0-3（≥1.5 优质）
    ├ ★authority    权威性 0-4（≥3 极权威，-1 未知）
    ├ ★date         发布时间（UTC RFC 3339）
    ├ ★content      网页正文（need_content=true 时返回）
    └ site_name     站点名
  brand_hits     品牌命中统计（自动匹配 own_brands + competitors）
  total_results  该 query 的结果总数
"""

import argparse, json, os, sys, time
from pathlib import Path
from datetime import datetime

# ─── 配置 ───
try:
    from openai import OpenAI
except ImportError:
    # DeepSeek API 兼容 OpenAI 格式
    os.system(f"{sys.executable} -m pip install openai -q")
    from openai import OpenAI

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    # 尝试从本地文件读取
    key_file = Path(__file__).parent / "data" / ".ds_api_key"
    if key_file.exists():
        API_KEY = key_file.read_text().strip()
    else:
        print("[ERROR] 未找到 DEEPSEEK_API_KEY 环境变量，也找不到 data/.ds_api_key")
        print("  设置方式：export DEEPSEEK_API_KEY=sk-xxx")
        print("  或：将 key 写入 geo-lab/data/.ds_api_key 文件")
        sys.exit(1)

BASE_URL = "https://api.deepseek.com"
SEARCH_ENDPOINT = "/v1/tools/search"
FETCH_ENDPOINT = "/v1/tools/fetch"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


# ─── 核心函数 ───

def search(query, count=10, need_content=False, ori_question=""):
    """调用 DeepSeek Search API，返回结构化搜索结果"""
    payload = {
        "query": query[:128],
        "count": min(count, 50),
    }
    if ori_question:
        payload["ori_question"] = ori_question[:512]
    if need_content:
        payload["need_content"] = True

    resp = client.post(
        path=SEARCH_ENDPOINT,
        body=payload,
    )
    # DeepSeek SDK 可能不直接支持 tools/search，用 httpx 兜底
    import httpx
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    resp = httpx.post(
        f"{BASE_URL}{SEARCH_ENDPOINT}",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch(url):
    """调用 DeepSeek Fetch API，抓取单页 Markdown"""
    import httpx
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    resp = httpx.post(
        f"{BASE_URL}{FETCH_ENDPOINT}",
        json={"url": url[:8192]},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def analyze_results(results, own_brands, competitors):
    """分析搜索结果：品牌命中、域名分布、质量评分"""
    domain_counter = Counter()
    brand_hits = Counter()
    quality_dist = Counter()
    authority_dist = Counter()
    dates = []

    for r in results:
        blob = (r.get("title") or "") + " " + (r.get("snippet") or "") + " " + (r.get("content") or "")
        url = r.get("url") or ""
        d = url.split("/")[2].replace("www.", "") if url.startswith("http") and "/" in url else "?"
        domain_counter[d] += 1

        for b in own_brands:
            if b.lower() in blob.lower():
                brand_hits[f"[OWN] {b}"] += 1
        for c in competitors:
            if c.lower() in blob.lower():
                brand_hits[f"[COMP] {c}"] += 1

        rs = r.get("rerank_score", 0)
        if rs >= 1.5: quality_dist["优质(≥1.5)"] += 1
        elif rs >= 1.0: quality_dist["中等(1-1.5)"] += 1
        else: quality_dist["低(<1)"] += 1

        auth = r.get("authority", -1)
        if auth >= 3: authority_dist["极权威(≥3)"] += 1
        elif auth >= 1: authority_dist["中等(1-3)"] += 1
        elif auth >= 0: authority_dist["低(<1)"] += 1

        if r.get("date"):
            dates.append(r["date"][:10])

    return {
        "domains": dict(domain_counter.most_common(10)),
        "brand_hits": dict(brand_hits.most_common(15)),
        "quality_dist": dict(quality_dist),
        "authority_dist": dict(authority_dist),
        "date_range": [min(dates) if dates else None, max(dates) if dates else None],
    }


def geo_scout(queries, own_brands, competitors, need_content=False):
    """对一组 query 执行搜索 + 分析"""
    all_results = []
    import httpx

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    for i, q in enumerate(queries, 1):
        try:
            payload = {"query": q[:128], "count": 10}
            if need_content:
                payload["need_content"] = True

            resp = httpx.post(
                f"{BASE_URL}{SEARCH_ENDPOINT}",
                json=payload,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])

            # 分析
            analysis = analyze_results(results, own_brands, competitors)

            record = {
                "query": q,
                "ts": datetime.now().isoformat(timespec="seconds"),
                "total_results": len(results),
                "results": results,
                "analysis": analysis,
            }
            all_results.append(record)

            # 提取品牌命中（简报）
            sg = analysis["brand_hits"].get("[OWN] 水裹", 0) or analysis["brand_hits"].get("[OWN] 松胜", 0) or \
                 analysis["brand_hits"].get("[OWN] 斐驰", 0)
            top_comp = {k.replace("[COMP] ", ""): v for k, v in analysis["brand_hits"].items() if k.startswith("[COMP]")}
            top_comp_str = ", ".join(f"{k}:{v}" for k, v in sorted(top_comp.items(), key=lambda x: -x[1])[:3])
            print(f"  [{i}/{len(queries)}] {q} → {len(results)} 条结果"
                  + (f" | 本品牌命中 {sg}" if sg else "")
                  + (f" | 竞品: {top_comp_str}" if top_comp_str else ""))

            # 限速 5 QPS
            time.sleep(0.25)

        except Exception as e:
            print(f"  [{i}/{len(queries)}] ERROR: {e}")
            time.sleep(1)

    return all_results


def main():
    ap = argparse.ArgumentParser(description="DeepSeek Search API GEO 侦察")
    ap.add_argument("--prompts", default="", help="题库 JSON 文件（从 prompt.text 提取 query）")
    ap.add_argument("--queries", default="", help="逗号分隔的搜索词（如无 --prompts 则使用此项）")
    ap.add_argument("--own", default="", help="本品牌别名（逗号分隔），覆盖题库 meta")
    ap.add_argument("--competitors", default="", help="竞品别名（逗号分隔），覆盖题库 meta")
    ap.add_argument("--out", default="", help="输出 JSONL 文件路径")
    ap.add_argument("--content", action="store_true", help="是否抓取网页正文（增加 token 但分析更深）")
    args = ap.parse_args()

    queries = []
    own_brands = []
    competitors = []

    if args.prompts:
        data = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
        meta = data.get("meta") or {}
        queries = [p["text"] for p in data.get("prompts", [])]
        own_brands = [str(b) for b in meta.get("own_brand", [])]
        competitors = [str(c) for c in meta.get("competitors", [])]
    elif args.queries:
        queries = [q.strip() for q in args.queries.split(",") if q.strip()]

    if args.own:
        own_brands = [b.strip() for b in args.own.split(",")]
    if args.competitors:
        competitors = [c.strip() for c in args.competitors.split(",")]

    if not queries:
        print("无搜索词。用 --prompts 或 --queries 指定。")
        sys.exit(1)

    print(f"DS GeoScout | {len(queries)} 个搜索词 | 本品牌: {own_brands} | 竞品 {len(competitors)} 项")
    print(f"成本估算: {len(queries)} 次 × 0.005 元 = {len(queries) * 0.005:.2f} 元")
    print()

    results = geo_scout(queries, own_brands, competitors)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in results),
            encoding="utf-8"
        )
        print(f"\n结果已写入: {out_path} ({len(results)} 条)")


if __name__ == "__main__":
    main()
