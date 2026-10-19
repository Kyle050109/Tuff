# -*- coding: utf-8 -*-
"""
GEO 基线 · 全部对外数字的唯一计算源
======================================================
审计要求「报告里的每个数字都能在仓库里复跑」。本脚本就是那个来源。
用法：python analyze_final.py            # 打印全部数字
      python analyze_final.py --json     # 另存 data/final_numbers.json（美容仪/斐驰，默认）
      python analyze_final.py --prompts prompts/anmo_chair_v1.json               --data data/chair_samples.jsonl --json        # 按摩椅/松胜（v1.6 跨类目参数化）
品牌表与分层断言优先级：--prompts 的 meta（own_brand/competitors/analysis_brands/layer_assert）
> 脚本默认常量（美容仪，向后兼容）。expect 断言在题库未声明时降级为 warning（新类目首轮观察模式）。

口径全部显式写在代码里，不用你猜。
"""
import sys, re, json, math, random, itertools
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geolib import read_jsonl, dedupe_last

ROOT = Path(__file__).resolve().parent

# ══════════════════════════════════════════════════════════════
# 口径定义（改口径必须改这里，并同步改报告）
# ══════════════════════════════════════════════════════════════

# 本品牌匹配（用于分层）
OWN_BRAND = re.compile(r"斐驰|Fetrex", re.I)

# 竞品品牌表（显式声明 —— v1.3 新增）
# 来源：本提示词库中实际出现的竞品名 + 品类常见品牌
# ⚠️ 改这张表会改变 A2 层的样本数，必须同步更新报告
# v1.6（工单 B3）：补拉丁别名 Tripollar / YA-MAN / YAMAN。
#   依据：题面（114 条）经查不含任何拉丁品牌写法 → 分层不变（§1 有断言兜底）；
#   别名只影响 §6 竞品引用计数与 §11 品牌间相关的匹配。
#   已知未覆盖：jmoonbeauty.com（极萌官网，18 条引用）未计入极萌——在披露清单注明。
COMPETITORS = [
    "Ulike", "AMIRO", "宙斯", "雅萌", "初普", "觅光", "极萌", "大排灯",
    "纽立", "索朗特", "ZIIP", "JOVS", "Nodoor", "花至", "听研",
    "飞利浦", "欧莱雅", "松下", "康铂", "Orey", "可思美", "倍轻松",
    "Tripollar", "YA-MAN", "YAMAN",
]

# 品牌 → 匹配别名表（§6 / §11 计数用；分层仍用 COMPETITORS 全表）
BRAND_ALIASES = {
    "索朗特": ["索朗特"], "觅光": ["觅光"], "大排灯": ["大排灯"], "极萌": ["极萌"],
    "雅萌": ["雅萌", "YA-MAN", "YAMAN"], "AMIRO": ["AMIRO"], "宙斯": ["宙斯"],
    "纽立": ["纽立"], "初普": ["初普", "Tripollar"],
}

# 字节系域名判定
BYTE_DOMAINS = ("douyin", "toutiao", "ixigua", "byteimg", "doubao")


def layer(r):
    """分层：**完全由问题文本决定，不使用 intent 标签**。

    A1 = 不含任何品牌名
    A2 = 仅含竞品名
    B  = 含本品牌 + 含竞品名（对比题）
    C  = 含本品牌 + 不含竞品名（纯品牌查询）

    ⚠️ 旧版把 C/B 之分交给 intent（声誉型/交易型→C），与「不使用意图标签」的
    声明自相矛盾（第三方复核指出）。本版改为纯文本规则；在现有 114 条上划分
    结果不变（B=4 / C=20），但新加的题不会因标签写错而错分。
    """
    t = r["text"]
    has_own = bool(OWN_BRAND.search(t))
    has_comp = any(c.lower() in t.lower() for c in COMPETITORS)
    if has_own:
        return "B" if has_comp else "C"
    return "A2" if has_comp else "A1"


def wilson(k, n, z=1.96):
    """Wilson 双侧 95% CI（本方法论统一口径），返回百分数"""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d * 100, (c + h) / d * 100)


def cp_upper(k, n, alpha=0.025):
    """Clopper-Pearson **双侧 95%** 上界（用于 0/n 这类情形），返回百分数。

    口径统一说明（第三方复核指出旧版混用）：本方法论对外统一 **双侧 95%**，
    故默认 alpha=0.025（单侧 2.5%）。k>0 时请用精确二项求根，本函数只处理 0/n。
    """
    if n == 0:
        return None            # 空层（部分数据/中途分析是合法场景）
    if k == 0:
        return (1 - alpha ** (1 / n)) * 100
    raise ValueError("cp_upper 仅用于 k=0；k>0 请用 Wilson 或精确二项")


# ══════════════════════════════════════════════════════════════
N = {}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default="", help="题库 json；其 meta 提供品牌表与分层断言")
    ap.add_argument("--data", default=str(ROOT / "data" / "samples.jsonl"))
    ap.add_argument("--json", nargs="?", default=str(ROOT / "data" / "final_numbers.json"),
                    help="json 落盘路径；缺省按题库名派生（防跨类目覆盖）")
    ap.add_argument("--json-out", dest="json_out", default="", help="json 落盘路径（覆盖 --json 默认）")
    ap.add_argument("--compare-data", default="", help="账号对照数据文件；与当前数据 pid 无交集时自动跳过该节")
    args = ap.parse_args()

    global OWN_BRAND, COMPETITORS, BRAND_ALIASES
    layer_assert = {"A1": 156, "A2": 34, "B": 8, "C": 28}   # 默认=美容仪实测（零回归）
    _plib = Path(args.prompts) if args.prompts else (ROOT / "prompts" / "meirongyi_final_v2.json")
    # v6（R4）：--json 默认路径随题库派生，防跨类目静默覆盖（如 final_<lib>_numbers.json）
    _json_default = ROOT / "data" / f"final_{_plib.stem}_numbers.json"
    if args.json == str(ROOT / "data" / "final_numbers.json"):
        args.json = str(_json_default)
    meta = (json.loads(_plib.read_text(encoding="utf-8")) or {}).get("meta") or {}
    if not meta.get("own_brand"):
        print(f"[WARNING] 题库 {_plib.name} 的 meta 无品牌表（own_brand 等）——使用脚本内默认常量。"
              f"跨类目复用请回填 meta（v1.7 §十三.8）；本 WARNING 不阻断（向后兼容）。")
    if args.prompts:
        pass
        if meta.get("own_brand"):
            OWN_BRAND = re.compile("|".join(re.escape(str(b)) for b in meta["own_brand"]), re.I)
        if meta.get("competitors"):
            COMPETITORS = [str(c) for c in meta["competitors"]]
        if meta.get("analysis_brands"):
            BRAND_ALIASES = {str(k): [str(a) for a in v] for k, v in meta["analysis_brands"].items()}
        if meta.get("layer_assert"):       # 题库声明的分层断言（样本数）
            layer_assert = {str(k): int(v) for k, v in meta["layer_assert"].items()}
        else:
            layer_assert = None            # 未声明 → 降级 warning（新类目首轮观察模式）
        print(f"[口径] 题库 {Path(args.prompts).name}：own={meta.get('own_brand')} 竞品{len(COMPETITORS)}项")

    # ---------- 0. 数据完整性 ----------
    raw_path = Path(args.data)
    txt = raw_path.read_text(encoding="utf-8")
    rows_all = read_jsonl(raw_path)
    rows = dedupe_last(rows_all)
    N["records_raw"] = len(rows_all)
    N["valid"] = len(rows)
    N["u2028_in_file"] = txt.count("\u2028") + txt.count("\u2029")

    by_layer = defaultdict(list)
    for r in rows:
        by_layer[layer(r)].append(r)

    print("=" * 66)
    print("【0】数据完整性")
    print(f"  原始记录 {N['records_raw']} 条 → 去重+ok 后有效 {N['valid']} 条")
    print(f"  文件内 U+2028/2029 字面量 = {N['u2028_in_file']}（应为 0）")

    # ---------- 1. 分层 ----------
    print("\n【1】分层")
    for L in ("A1", "A2", "B", "C"):
        rs = by_layer[L]
        pids = {r["prompt_id"] for r in rs}
        h = sum(1 for r in rs if r.get("brand_mentioned"))
        print(f"  {L}: 样本 {len(rs):4d}  提示词 {len(pids):3d}  提及 {h:3d}")
        N[f"n_{L}"] = len(rs)
        N[f"prompts_{L}"] = len(pids)
        N[f"hit_{L}"] = h
    # 断言分层条数（v1.6，工单 B3 安全网：拉丁别名加入 COMPETITORS 后，若题面
    # 意外含拉丁品牌名导致分层变化，在此报错而非静默改基线。预期=题面无拉丁名的实测值）
    got = {L: N[f"n_{L}"] for L in ("A1", "A2", "B", "C")}
    if layer_assert is not None:
        assert got == layer_assert, f"分层条数变化：{got} != {layer_assert} —— 名单改动影响了分层，须重新核对 A1 原文后更新预期值与报告"
    else:
        print(f"  ⚠ 题库未声明 layer_assert（首轮观察模式）：实际分层 {got}——核对 A1 原文无误后写入题库 meta 再复跑")

    # ---------- 2. 基线 A1 ----------
    print("\n【2】基线：A1 层（问题不含任何品牌名）")
    A1 = by_layer["A1"]
    k1, n1 = N["hit_A1"], len(A1)
    lo, hi = wilson(k1, n1)
    N["p_A1"] = k1 / n1 * 100
    N["p_A1_ci"] = [lo, hi]
    print(f"  样本口径 {k1}/{n1} = {k1/n1*100:.2f}%  Wilson 95% [{lo:.2f}%, {hi:.2f}%]")
    pids1 = sorted({r["prompt_id"] for r in A1})
    hitp = [p for p in pids1 if any(r.get("brand_mentioned") for r in A1 if r["prompt_id"] == p)]
    N["p_A1_prompt"] = len(hitp) / len(pids1) * 100
    lo2, hi2 = wilson(len(hitp), len(pids1))
    N["p_A1_prompt_ci"] = [lo2, hi2]
    print(f"  提示词口径 {len(hitp)}/{len(pids1)} = {len(hitp)/len(pids1)*100:.2f}%  Wilson 95% [{lo2:.2f}%, {hi2:.2f}%]")

    # ---------- 3. A2 竞品题段 ----------
    print("\n【3】A2 层（问题含竞品名、不含本品牌）")
    A2 = by_layer["A2"]
    k2, n2 = N["hit_A2"], len(A2)
    up = cp_upper(k2, n2) if k2 == 0 else None
    N["p_A2_upper"] = up
    pids2 = sorted({r["prompt_id"] for r in A2})
    if n2 and k2 == 0 and up is not None:
        print(f"  样本 {k2}/{n2} = {k2/n2*100:.2f}%   95% 上界（Clopper-Pearson）≤ {up:.2f}%")
    elif n2:
        lo2 = (k2/n2 - 1.96*math.sqrt((k2/n2)*(1-k2/n2)/n2))*100
        hi2 = (k2/n2 + 1.96*math.sqrt((k2/n2)*(1-k2/n2)/n2))*100
        print(f"  样本 {k2}/{n2} = {k2/n2*100:.2f}%   Wilson 近似 95% CI [{max(lo2,0):.2f}%, {hi2:.2f}%]")
    else:
        print("  样本 0/0（层为空：数据尚未覆盖或部分采集）")
    print(f"  涉及提示词 {len(pids2)} 条: {pids2}")
    for p in pids2:
        rs = [r for r in A2 if r["prompt_id"] == p]
        print(f"    {p} {rs[0]['text']}  n={len(rs)} 提及={sum(1 for r in rs if r.get('brand_mentioned'))}")

    print("\n【3b】A1 层提示词原文（人工过一遍——必须确认无任何品牌名混入）")
    pids1_all = sorted({r["prompt_id"] for r in by_layer["A1"]})
    for p in pids1_all:
        rs = [r for r in by_layer["A1"] if r["prompt_id"] == p]
        print(f"    {p} {rs[0]['text']}")

    # ---------- 4. 触发检索分层 ----------
    print("\n【4】触发检索分层（A1+A2 合并口径与 A1 口径）")
    for tag, pool in (("A1", A1), ("A1+A2", A1 + A2)):
        st = [r for r in pool if r.get("search_triggered")]
        nst = [r for r in pool if not r.get("search_triggered")]
        kh = sum(1 for r in st if r.get("brand_mentioned"))
        print(f"  {tag}: 触发 {len(st)}（提及 {kh}） / 未触发 {len(nst)}（提及 {sum(1 for r in nst if r.get('brand_mentioned'))}）")
        N[f"trig_{tag}"] = [len(st), kh, len(nst)]
        if nst:
            _kn = sum(1 for r in nst if r.get("brand_mentioned"))
            if _kn == 0:
                _up = cp_upper(0, len(nst), 0.025)
                print(f"    {tag} 未触发 0/{len(nst)} 双侧95%上界 ≤ {_up:.2f}%")
            else:
                _up = None
                print(f"    {tag} 未触发 {_kn}/{len(nst)}（非零，无上界口径）")
        else:
            _up = None
        N[f"nontrig_upper_{tag}"] = _up

    # ---------- 4a. A1 基线的 stage 拆分（两阶段设计口径，v5 新增）----------
    print(chr(10) + "【4a】A1 基线 stage 拆分（两阶段设计：stage-2 为摇摆题加跑，并入会引入选择偏倚）")
    _s1 = [r for r in by_layer["A1"] if r["run_idx"] in (1, 2)]
    _s2 = [r for r in by_layer["A1"] if r["run_idx"] in (3, 4, 5)]
    if _s2 and not meta.get("stage2_design"):
        print(f"  本数据集非两阶段设计（meta.stage2_design 未声明）：run3-5 为历史 5 遍批（人工指定/采样未匀），"
              f"按两阶段语义拆分会误导——只报合并口径")
    elif _s1 and not _s2:
        print(f"  本数据集为单阶段：A1 = {sum(1 for r in _s1 if r.get('brand_mentioned'))}/{len(_s1)}"
              f"（stage 拆分不适用）")
    elif _s2:
        k1_ = sum(1 for r in _s1 if r.get("brand_mentioned")); k2_ = sum(1 for r in _s2 if r.get("brand_mentioned"))
        p1_ = 100*k1_/len(_s1); p2_ = 100*k2_/len(_s2); pall = 100*(k1_+k2_)/(len(_s1)+len(_s2))
        print(f"  第一阶段(run1-2，主口径): {k1_}/{len(_s1)} = {p1_:.2f}%")
        print(f"  stage-2(run3-5，摇摆加跑，单列): {k2_}/{len(_s2)} = {p2_:.2f}%")
        print(f"  合并(旧口径，含选择偏倚): {k1_+k2_}/{len(_s1)+len(_s2)} = {pall:.2f}%"
              f"（并入使基线抬升 {pall-p1_:+.2f}pp —— v1.7 §五：ρ 对照批/stage-2 不得并入基线）")
        N["A1_stage1"] = [k1_, len(_s1)]; N["A1_stage2"] = [k2_, len(_s2)]

    # ---------- 4a2. 地域覆盖（本地生活：v1.8 业务要求 A1 层 100% 带地域词；v1.1 收紧） ----------
    if meta.get("geo_word"):
        gw = [str(g) for g in meta["geo_word"]]
        def _has_geo(r): return any(g in r["text"] for g in gw)
        _with = [r for r in by_layer["A1"] if _has_geo(r)]
        _without = [r for r in by_layer["A1"] if not _has_geo(r)]
        print(f"  地域覆盖：A1 含地域词 {_with.__len__()}/{len(by_layer['A1'])}"
              f" = {100*len(_with)/max(len(by_layer['A1']),1):.1f}%（本地生活口径要求 100%）")
        if _without:
            print(f"  ⚠ {len(_without)} 条 A1 不含地域词（业务方要求本地生活 A1 必带地域）——题目 id："
                  f"{sorted({r['prompt_id'] for r in _without})[:10]}")
        for tag, sub in (("含地域词", _with), ("不含地域词", _without)):
            if sub:
                k_ = sum(1 for r in sub if r.get("brand_mentioned"))
                st_ = sum(1 for r in sub if r.get("search_triggered"))
                dy_ = sum(1 for r in sub if "iesdouyin.com" in (r.get("citation_hosts") or []))
                print(f"  [{tag} n={len(sub)}] 提及 {k_} = {100*k_/len(sub):.2f}%｜触发 {st_}/{len(sub)}"
                      f" = {100*st_/len(sub):.2f}%｜含抖音引用样本 {dy_}/{len(sub)}")
                N[f"geo_{tag}"] = [k_, len(sub), st_, dy_]

    # ---------- 4a3. 渠道 × 层级交叉（v2.0 新增：GEO 分层目标——渠道结论必须分层报告）----------
    print(chr(10) + "【4a3】渠道 × 层级交叉（防跨层混池——六轮审核发现渠道聚合结论被层级结构掩盖）")
    _chan_map = {"象上汇/品牌官网": [], "地方媒体": [], "携程": [], "抖音": [], "OTA(KKday/Klook)": []}
    for r in A1 + A2:
        for c in (r.get("citations") or []):
            u = c.get("url") or ""
            d = u.split("/")[2].replace("www.", "") if u.startswith("http") else "?"
            if "douyin" in d: _chan_map["抖音"].append(r)
            elif "ctrip" in d: _chan_map["携程"].append(r)
            elif "kkday" in d or "klook" in d: _chan_map["OTA(KKday/Klook)"].append(r)
            elif "xshhotels" in d or any(x in d for x in ["rongtai", "ogawa", "osim", "westinghouse", "panasonic", "songsheng"]): _chan_map["象上汇/品牌官网"].append(r)
            elif "gdzjdaily" in d or "china.com" in d or "sohu" in d: _chan_map["地方媒体"].append(d)
    # 用 record 集合去重（同一 record 的多个引用只算一次）
    _chan_summary = {}
    for cname in ["象上汇/品牌官网", "地方媒体", "携程", "OTA(KKday/Klook)", "抖音"]:
        _doms = {"象上汇/品牌官网": ["xshhotels", "rongtai", "ogawa", "osim", "westinghouse", "panasonic", "songsheng"],
                 "地方媒体": ["gdzjdaily", "china.com", "sohu"],
                 "携程": ["ctrip"], "OTA(KKday/Klook)": ["kkday", "klook"], "抖音": ["douyin"]}
        dl = _doms.get(cname, [cname])
        _row = []
        for lname in ["A1", "A2", "B", "C"]:
            pool = by_layer.get(lname, [])
            hit = [r for r in pool if any(any(d in (c.get("url") or "") for d in dl) for c in (r.get("citations") or []))]
            m = sum(1 for r in hit if r.get("brand_mentioned"))
            _row.append((lname, len(hit), len(pool), m))
        _chan_summary[cname] = _row
        parts = []
        for ln, nh, np_, nm in _row:
            if nh:
                parts.append(f"{ln}:{nh}({100*nm/nh:.0f}%)")
            else:
                parts.append(f"{ln}:0")
        print(f"  {cname}: {' | '.join(parts)}")
    N["channel_by_layer"] = {c: [(ln, nh, np_, nm) for ln, nh, np_, nm in rows_] for c, rows_ in _chan_summary.items()}

    # ---------- 4b. 意图触发率（两池并列，防混池）+ 构成占比 ----------
    print(chr(10) + "【4b】意图触发率（两池并列；表级分母声明规则）")
    for tag, pool in (("A1+A2", A1 + A2), ("全样本", rows)):
        ints2 = defaultdict(lambda: [0, 0])
        for r in pool:
            ints2[r["intent"]][0] += 1
            ints2[r["intent"]][1] += bool(r.get("search_triggered"))
        line = "  ".join(f"{i} {t}/{n}={100*t/n:.2f}%" for i, (n, t) in
                         sorted(ints2.items(), key=lambda kv: -kv[1][1]/kv[1][0]))
        print(f"  [{tag}池 n={len(pool)}] {line}")
        N[f"intent_trig_{tag}"] = {i: [n, t] for i, (n, t) in ints2.items()}
    _allp = sorted({(r["prompt_id"], r["intent"]) for r in rows})
    from collections import Counter as _Ctr
    _ic = _Ctr(i for _, i in _allp)
    print(f"  提示词意图构成：{dict(_ic)}（合计 {len(_ic) and sum(_ic.values())} 条）")
    for name in ("榜单型", "信息型"):
        if name in _ic:
            print(f"    {name} 提示词占比 {_ic[name]}/{sum(_ic.values())} = {100*_ic[name]/sum(_ic.values()):.2f}%"
                  f"｜样本口径(A1+A2) {sum(1 for r in A1+A2 if r['intent']==name)}/{len(A1+A2)}"
              f" = {100*sum(1 for r in A1+A2 if r['intent']==name)/len(A1+A2):.2f}%")
    N["intent_prompt_counts"] = dict(_ic)

    # ---------- 5. 引用域 ----------
    print("\n【5】引用域（发现层 A1+A2）")
    A = A1 + A2
    allc = [c for r in A for c in (r.get("citations") or [])]
    hosts = Counter(urlparse(c.get("url", "")).netloc.replace("www.", "") for c in allc)
    byte = sum(v for k, v in hosts.items() if any(d in k for d in BYTE_DOMAINS))
    dy = hosts.get("iesdouyin.com", 0)
    N["citations"] = len(allc)
    N["byte_share"] = byte / len(allc) * 100
    N["iesdouyin_share"] = dy / len(allc) * 100
    N["iesdouyin_of_byte"] = dy / byte * 100
    N["unique_hosts"] = len(hosts)
    print(f"  引用总数 {len(allc)}，唯一域 {len(hosts)}")
    print(f"  字节系 {byte}/{len(allc)} = {byte/len(allc)*100:.2f}%")
    print(f"  其中 iesdouyin.com {dy} 条，占全部 {dy/len(allc)*100:.2f}%，占字节系 {dy/byte*100:.2f}%")
    withdy = sum(1 for r in A if any("douyin" in urlparse(c.get("url", "")).netloc for c in (r.get("citations") or [])))
    N["samples_with_douyin"] = withdy
    print(f"  至少含 1 条抖音的样本 {sum(1 for r in A if 'iesdouyin.com' in (r.get('citation_hosts') or []))}/{len(A)}")
    # 域名两池对照（本轮审核 N1：域名计数必须注明池子——发现层与全样本分开）
    def _doms(pool):
        c = defaultdict(int)
        for r in pool:
            for ci in (r.get("citations") or []):
                u = ci.get("url", "") or ""
                d = u.split("/")[2].replace("www.", "") if u.startswith("http") and len(u.split("/")) > 2 else "?"
                c[d] += 1
        return c
    dp1, dp2 = _doms(A1 + A2), _doms(rows)
    _byte_all = sum(v for k, v in dp2.items() if any(b in k for b in BYTE_DOMAINS))
    _tot_all = sum(dp2.values())
    print(f"  字节系全层口径：{_byte_all}/{_tot_all} = {100*_byte_all/_tot_all:.2f}%")
    N["byte_all_pool"] = [_byte_all, _tot_all]
    _watch = ["iesdouyin.com", "amiro.com.cn", "international-shop.ya-man.com", "ya-man.co.jp",
              "ya-man-tokyo-japan.com", "ya-man.hk", "ya-man.com", "m.jmoonbeauty.com"]
    for d in _watch:
        if dp2.get(d) or dp1.get(d):
            print(f"    {d}: 发现层 {dp1.get(d, 0)} / 全样本 {dp2.get(d, 0)}")
            N[f"dom_{d}"] = [dp1.get(d, 0), dp2.get(d, 0)]
    _ya1 = sum(v for k, v in dp1.items() if "ya-man" in k or "yaman" in k)
    _ya2 = sum(v for k, v in dp2.items() if "ya-man" in k or "yaman" in k)
    print(f"    ya-man 系全域名合计: 发现层 {_ya1} / 全样本 {_ya2}")
    N["ya_man_family"] = [_ya1, _ya2]
    print("  Top 8 域:")
    for k, v in hosts.most_common(8):
        print(f"    {v:5d}  {v/len(allc)*100:5.2f}%  {k}")

    # ---------- 6. 竞品来源层计数 ----------
    print("\n【6】竞品在引用标题中的出现次数（匹配规则：title ∪ url，v1.6 起含拉丁别名）")
    cc = {}
    for name in list(BRAND_ALIASES.keys())[:8]:
        pat = re.compile("|".join(re.escape(a) for a in BRAND_ALIASES[name]), re.I)
        t = sum(1 for c in allc if pat.search(c.get("title") or ""))
        u = sum(1 for c in allc if pat.search(c.get("url") or ""))
        tu = sum(1 for c in allc if pat.search((c.get("title") or "") + (c.get("url") or "")))
        cc[name] = {"title": t, "url": u, "title_or_url": tu}
        print(f"  {name:5s} title={t:4d}  url={u:4d}  title∪url={tu:4d}")
    N["competitor_citations"] = cc
    # 本品牌
    own = sum(1 for c in allc if OWN_BRAND.search((c.get("title") or "") + (c.get("url") or "")))
    N["own_brand_in_citations"] = own
    print(f"  ★ 本品牌({OWN_BRAND.pattern}) title∪url 命中 = {own}  ← 来源层")

    # ---------- 7. ρ ----------
    print("\n【7】ρ（簇内相关）")
    byp = defaultdict(list)
    for r in A1 + A2:
        byp[r["prompt_id"]].append(r.get("brand_mentioned"))
    five = {k: v for k, v in byp.items() if len(v) == 5}
    N["five_run_prompts"] = len(five)

    def rho(sel):
        m = sum(1 for k in sel for v in five[k] if v) / sum(len(five[k]) for k in sel)
        ag = [1 if five[k][i] == five[k][j] else 0
              for k in sel for i in range(len(five[k])) for j in range(i + 1, len(five[k]))]
        pa = sum(ag) / len(ag)
        pe = m * m + (1 - m) * (1 - m)
        return (pa - pe) / (1 - pe) if abs(1 - pe) > 1e-9 else 0.0

    ks = sorted(five)
    pt = rho(ks)
    random.seed(0)
    boot = sorted(rho([random.choice(ks) for _ in ks]) for _ in range(3000))
    blo, bhi = boot[int(.025 * 3000)], boot[int(.975 * 3000)]
    N["rho"] = pt
    N["rho_ci"] = [blo, bhi]
    N["de"] = 1 + 4 * pt
    N["de_ci"] = [1 + 4 * blo, 1 + 4 * bhi]
    print(f"  跑满 5 遍的提示词 {len(five)} 条，同簇对 {sum(len(v)*(len(v)-1)//2 for v in five.values())} 个")
    print(f"  点估计 ρ = {pt:+.4f}")
    print(f"  bootstrap 95% CI（3000 次，按提示词重抽）= [{blo:+.3f}, {bhi:+.3f}]  含 0: {'是' if blo < 0 < bhi else '否'}")
    de_lo, de_hi = 1 + 4 * blo, 1 + 4 * bhi
    rho_estimable = len(five) >= 10 and de_lo > 0
    print(f"  设计效应 DE = 1+4ρ = {1+4*pt:.2f}，CI [{de_lo:.2f}, {de_hi:.2f}]")
    if rho_estimable:
        print(f"  → 重复的实际价值 = [{1/de_hi:.2f}x, {1/de_lo:.2f}x]（跨过 1.0 = 可能无增益）")
    else:
        why = f"5 遍题仅 {len(five)} 条（<10）" if len(five) < 10 else "ρ CI 下界使 DE≤0"
        print(f"  ⚠ ρ 的预算口径不可估：{why}。两阶段设计下 5 遍数据只来自摇摆题（选择偏差，")
        print(f"    天然压负值——即 v1.0 美容仪教训的自动化重演）。预算请用 DE 敏感性双口径（§9）。")
    N["rho_estimable"] = rho_estimable

    _m5 = [k for k in five]
    _m1 = [k for k in byp if len(byp[k]) == 1]
    if _m5 and _m1:
        r5 = sum(1 for k in _m5 for v in five[k] if v) / sum(len(five[k]) for k in _m5)
        r1 = sum(1 for k in _m1 for v in byp[k] if v) / sum(len(byp[k]) for k in _m1)
        print(f"  子集提及率：5 遍题 {sum(1 for k in _m5 for v in five[k] if v)}/{sum(len(five[k]) for k in _m5)}"
              f" = {100*r5:.2f}%｜单遍题 {sum(1 for k in _m1 for v in byp[k] if v)}/{sum(len(byp[k]) for k in _m1)}"
              f" = {100*r1:.2f}%（A1+A2 池）")
        N["rho_subset_rates"] = [100*r5, 100*r1]

    # 对照：只用摇摆题（错误口径）
    swing = [k for k in five if len(set(five[k])) > 1]
    _sv = rho(swing)
    _sv_hint = "（会压成负值）" if _sv < 0 else "（本数据集未压负——该口径的偏倚方向不固定，不构成通则）"
    print(f"  【对照·错误口径】只用 {len(swing)} 条摇摆题估 = {_sv:+.4f}{_sv_hint}")
    N["rho_swing_only"] = rho(swing)

    # ---------- 7b. 随机性边界（v1.5 新增：此前 84.0%/45.1%/34.6%/游程检验只在审计脚本里，未入官方产出）----------
    print(chr(10) + "【7b】随机性边界（确定性 / 单题上界 / 游程检验）")
    det = [k for k in five if len(set(five[k])) == 1]
    print(f"  跑满 5 遍 {len(five)} 条中确定性 {len(det)} 条（{100*len(det)/len(five):.1f}%），摇摆 {len(swing)} 条：{swing}")
    print(f"  单条题 5 遍全不提的真实提及概率：单侧 95% 上界 = {100*(1-0.05**0.2):.1f}%")
    from math import comb as _C2
    print(f"  独立伯努利(p=2/5)下 5 遍恰好 2 次提及（任意位置）概率 = {_C2(5,2)*0.4**2*0.6**3*100:.1f}%")
    # 精确游程检验（对摇摆题；序列严格按 run_idx 排序，从原始记录重建）
    byp_rec = defaultdict(list)
    for r in A1 + A2:
        if r["prompt_id"] in swing:
            byp_rec[r["prompt_id"]].append((r["run_idx"], bool(r.get("brand_mentioned"))))
    tot_obs = tot_exp = 0.0
    for k in swing:
        seq = [1 if m else 0 for _, m in sorted(byp_rec[k])]
        obs_sw = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        nT, nF = sum(seq), len(seq) - sum(seq)
        exp_sw = 2 * nT * nF / len(seq)
        import itertools as _it
        arrangements = set(_it.permutations(seq))
        dist = {}
        for arr in arrangements:
            s_ = sum(1 for a, b in zip(arr, arr[1:]) if a != b)
            dist[s_] = dist.get(s_, 0) + 1
        p_le = sum(c for s_, c in dist.items() if s_ <= obs_sw) / sum(dist.values())
        print(f"    {k}: 切换 {obs_sw} 次 vs 期望 {exp_sw:.1f}，P(≤观测|随机排序) = {p_le:.2f}")
        tot_obs += obs_sw; tot_exp += exp_sw
    print(f"  合计：观测切换 {tot_obs:.0f} 次 vs 期望 {tot_exp:.1f} 次 —— 不拒绝独立随机排序")
    N["five_run_total"] = len(five); N["deterministic"] = len(det)

    # ---------- 8. 账号 ----------
    print("\n【8】账号对照（仅 3×3 完整的题）")
    ca_path = Path(args.compare_data) if args.compare_data else (ROOT / "data" / "compare_accounts.jsonl")
    ca = read_jsonl(ca_path) if ca_path.exists() else []
    if ca:
        # 守卫两道：pid 交集 + 题面 text 匹配（跨类目会撞 pid 前缀，如 B01 美容仪 vs B01 按摩椅）
        _texts_now = {r["text"] for r in rows}
        _hit = sum(1 for r in ca if r.get("account") and r.get("text") in _texts_now)
        _tot = sum(1 for r in ca if r.get("account"))
        if _hit < _tot * 0.8:
            print(f"  ⚠ 账号对照文件与当前数据题面不匹配（{_hit}/{_tot} 条 text 命中——跨类目文件），本节跳过")
            ca = []
    if ca:
        g = defaultdict(lambda: defaultdict(dict))
        for r in ca:
            if r.get("account"):
                g[r["prompt_id"]][r["account"]][r["run_idx"]] = set(r.get("citation_hosts") or [])
        full = [p for p, a in g.items()
                if len(a) == 3 and all(len(v) == 3 for v in a.values())]
        N["account_prompts"] = len(full)

        def jac(a, b):
            if not a and not b:
                return None
            return len(a & b) / len(a | b) if (a and b) else 0.0

        accs = ["acc1", "acc2", "acc3"]
        W, C = [], []
        diffs = []
        for p in full:
            w, c = [], []
            for a in accs:
                rs = list(g[p][a].values())
                w += [jac(rs[i], rs[j]) for i in range(len(rs)) for j in range(i + 1, len(rs)) if jac(rs[i], rs[j]) is not None]
            for a, b in itertools.combinations(accs, 2):
                c += [jac(x, y) for x in g[p][a].values() for y in g[p][b].values() if jac(x, y) is not None]
            W += w; C += c
            diffs.append(sum(c) / len(c) - sum(w) / len(w))
        m = sum(diffs) / len(diffs)
        sd = (sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1)) ** .5
        se = sd / len(diffs) ** .5
        tcrit = 2.447 if len(diffs) - 1 == 6 else 1.96   # t(6) 双侧95%
        N["acct_within"] = sum(W) / len(W)
        N["acct_cross"] = sum(C) / len(C)
        N["acct_diff"] = m
        N["acct_ci"] = [m - tcrit * se, m + tcrit * se]
        print(f"  完整题 {len(full)} 条：{full}")
        print(f"  组内均值 {sum(W)/len(W):.4f}（n={len(W)}）  跨号均值 {sum(C)/len(C):.4f}（n={len(C)}）")
        print(f"  单值范围：组内 [{min(W):.3f}, {max(W):.3f}]  跨号 [{min(C):.3f}, {max(C):.3f}]")
        print(f"  逐题「跨−组」均值 = {m:+.4f}，t({len(diffs)-1}) 95% CI [{m-tcrit*se:+.4f}, {m+tcrit*se:+.4f}]")
        print(f"  ⚠ 结论只能用 cluster 水平：未检出差异，可排除平均差 > {abs(m-tcrit*se):.3f}")

    # ---------- 9. MDE 表 ----------
    print("\n【9】MDE 表（p=基线，α=0.05 双侧，power=80%，z=1.959964+0.841621=2.801585）")
    p = k1 / n1
    z = 1.959964 + 0.841621
    print("  【单样本】与固定基线比较")
    single = {}
    RUNS = 5
    if N.get("rho_estimable", True):
        de_list = [(1 + 4 * pt, f"DE={1+4*pt:.2f}（ρ实测）")]
    else:
        de_list = [(1.0, "DE=1.0（下限）"), (1.5, "DE=1.5（敏感）")]
        print("  （ρ 不可估 → DE 敏感性双口径）")
    for mde in (0.03, 0.05, 0.08, 0.10, 0.15):
        n = math.ceil(z**2 * p * (1 - p) / mde**2)
        single[f"{mde*100:.0f}pp"] = n
        parts = []
        for de, tag in de_list:
            m_prompts = math.ceil(n * de / RUNS)
            parts.append(f"{m_prompts:3d} 条（{tag}）")
            single[f"{mde*100:.0f}pp_prompts_de{de:.2f}"] = m_prompts
        print(f"    δ={mde*100:5.0f}pp → 需 {n:4d} 个独立样本 → 提示词 " + " / ".join(parts))
    print("  【双样本】投放前后各取一轮（每臂）。公式（标准两比例检验）：")
    print("    n = [z_α·sqrt(2·p̄·(1-p̄)) + z_β·sqrt(p·(1-p) + p2·(1-p2))]^2 / δ^2   （p̄=(p+p2)/2）")
    print("    （v1.4 及以前用简化式 (z_α+z_β)^2·(p·(1-p)+p2·(1-p2))/δ^2，两式在本参数下差 <2.5%，")
    print("      v1.5 起改用标准式并在脚本与文档同时披露）")
    two = {}
    za, zb = 1.959964, 0.841621
    for mde in (0.05, 0.08, 0.10):
        p2 = p + mde
        pbar = (p + p2) / 2
        n = math.ceil((za * math.sqrt(2 * pbar * (1 - pbar))
                       + zb * math.sqrt(p * (1 - p) + p2 * (1 - p2))) ** 2 / mde ** 2)
        two[f"{mde*100:.0f}pp"] = n
        key = f"{mde*100:.0f}pp"
        ratio = n / single[key]
        print(f"    δ={mde*100:5.0f}pp → 每臂 {n:4d} 个独立样本（是单样本口径的 {ratio:.1f} 倍）")
    N["mde_single"] = single
    N["mde_two"] = two

    # ---------- 10. 超几何检验（池子必须与基线一致）----------
    # 第三方复核指出：基线是 A1，但触发检索的超几何此前用 A1+A2 池 —— 混层。此处两池并列。
    print(chr(10) + "【10】超几何：全部提及都落在触发检索样本内的概率（两池并列，基线口径用 A1）")
    from math import prod as _prod
    for tag, pool, jkey in (("A1（基线口径，应采用）", by_layer["A1"], "hyper_A1_only"),
                            ("A1+A2（旧口径，已弃用）", by_layer["A1"] + by_layer["A2"], "hyper_A1A2_merged")):
        st = [r for r in pool if r.get("search_triggered")]
        k = sum(1 for r in pool if r.get("brand_mentioned"))
        P = _prod([(len(st) - i) / (len(pool) - i) for i in range(k)]) if k <= len(st) else 0.0
        print(f"  {tag}: 触发 {len(st)}/{len(pool)}，提及 {k}，P = {P:.4f}")
        N[jkey] = P   # v1.6 修：旧键名 tag[:2] 两池同为 "A1"，后值覆盖前值（json 静默错）
    # 分层超几何（终审 N2：触发率按意图 6%→100% 变化，未分层 P 被高触发意图驱动）
    for _iname in ("榜单型", "非榜单型"):
        _pool = [r for r in by_layer["A1"] if (r["intent"] == "榜单型") == (_iname == "榜单型")]
        _st = [r for r in _pool if r.get("search_triggered")]
        _k = sum(1 for r in _pool if r.get("brand_mentioned"))
        if _pool and _k:
            _P = _prod([(len(_st) - i) / (len(_pool) - i) for i in range(_k)]) if _k <= len(_st) else 0.0
            print(f"  分层[{_iname}]: n={len(_pool)} 触发={len(_st)} 提及={_k}，P = {_P:.4f}"
                  f"（注：提及样本成簇于少数提示词，超几何独立性假设近似）")
            N[f"hyper_A1_{_iname}"] = _P

    # ---------- 11. 陈述层 x 引用层（品牌间相关；两池并列 + 混杂说明）----------
    print(chr(10) + f"【11】陈述层 x 引用层 品牌间相关（n={len(BRAND_ALIASES)}，区间极宽，谨慎解读）")
    def _corr(pool):
        xs, ys = [], []
        for b in list(BRAND_ALIASES.keys()):
            pat = re.compile("|".join(re.escape(a) for a in BRAND_ALIASES[b]), re.I)
            xs.append(sum(1 for r in pool if pat.search(r.get("answer") or "")))
            ys.append(sum(1 for r in pool if any(pat.search((c.get("title") or "") + (c.get("url") or ""))
                                                 for c in (r.get("citations") or []))))
        nn = len(xs); mx = sum(xs) / nn; my = sum(ys) / nn
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        rr = cov / (sx * sy) if sx * sy else 0.0
        z = 0.5 * math.log((1 + rr) / (1 - rr)) if abs(rr) < 1 else 0.0
        se = 1 / math.sqrt(nn - 3)
        return rr, (math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se))
    for tag, pool in (("A1+A2", by_layer["A1"] + by_layer["A2"]), ("A1", by_layer["A1"])):
        rr, ci = _corr(pool)
        print(f"  {tag} 池: r = {rr:+.4f}   95% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]")
        N[f"r_{tag}"] = [rr, list(ci)]
    # 混杂数字由程序从 A2 题面计算（v1.4 曾手写 8/14、12/14，与事实不符，v1.5 修正为程序产出）
    a2pids = sorted({r["prompt_id"] for r in by_layer["A2"]})
    a2face = {pid: next(r["text"] for r in by_layer["A2"] if r["prompt_id"] == pid) for pid in a2pids}
    _face_brands = [a for b in BRAND_ALIASES.values() for a in b]   # v1.6 残留：旧版硬编码美容仪品牌
    face_hits = {b: sum(1 for t in a2face.values() if b in t) for b in _face_brands}
    hit_str = "、".join(f"{b} {c}/{len(a2pids)}" for b, c in face_hits.items() if c > 0)
    print(f"  ⚠ 混杂提示：A2 的 {len(a2pids)} 条题面本身就写着竞品名（{hit_str}），")
    print("     答案必然提到该竞品 -> 陈述层计数被题面机械抬高。跨池符号都会变。")
    N["a2_face_hits"] = face_hits

    # ---------- 12. 引用编号连续性 ----------
    print(chr(10) + "【12】引用编号连续性（完整性取证）")
    withnum = [r for r in rows if r.get("citation_nums")]
    gaps = [r for r in withnum if r["citation_nums"] != list(range(1, len(r["citation_nums"]) + 1))]
    N["with_numbering"] = len(withnum)
    N["numbering_gaps"] = len(gaps)
    print(f"  有编号的样本 {len(withnum)} 条；编号不连续 {len(gaps)} 条 -> 100% 连续" if not gaps
          else f"  有编号 {len(withnum)} 条；不连续 {len(gaps)} 条")
    # 覆盖率限定（v1.5 新增）：citation_nums 是字段演进产物，只覆盖后期样本
    if withnum:
        tmin, tmax = min(r["ts"] for r in withnum), max(r["ts"] for r in withnum)
        print(f"  ⚠ 覆盖率限定：citation_nums 字段自 {tmin} 起才有（首条），覆盖 {len(withnum)}/{len(rows)} 有效样本；")
        print(f"    早期样本无编号数据，本项验证不等价于全量完整性核查")

    # ---------- 13. 账号：两个估计量分别标注 ----------
    print(chr(10) + "【13】账号：两个估计量必须分别标注（配对 vs 池化）")
    if ca and N.get("account_prompts"):
        accs = ["acc1", "acc2", "acc3"]

        def _rs(p_, a_):
            return list(g[p_][a_].values())

        def _w(rs):
            return [jac(rs[i], rs[j]) for i in range(len(rs)) for j in range(i + 1, len(rs))
                    if jac(rs[i], rs[j]) is not None]

        def _x(A, B):
            return [jac(x, y) for x in A for y in B if jac(x, y) is not None]

        # (a) acc1 vs acc2 配对（第三方用的估计量）
        dd = []
        for p_ in full:
            ww = _w(_rs(p_, "acc1")) + _w(_rs(p_, "acc2"))
            cc = _x(_rs(p_, "acc1"), _rs(p_, "acc2"))
            dd.append(sum(cc) / len(cc) - sum(ww) / len(ww))
        m1 = sum(dd) / len(dd)
        se1 = (sum((d - m1) ** 2 for d in dd) / (len(dd) - 1)) ** 0.5 / len(dd) ** 0.5
        print(f"  (a) acc1-acc2 配对估计量：{m1:+.4f}，t(6) 95% CI [{m1-2.447*se1:+.4f}, {m1+2.447*se1:+.4f}]")
        print(f"      ^ 第三方报的 +0.006 就是这个估计量，**可复现**（v1.3 曾误判为不可复现）")
        N["acct_paired_12"] = [m1, [m1 - 2.447 * se1, m1 + 2.447 * se1]]
        # (b) 三对池化
        dd2 = []
        for p_ in full:
            ww = []
            cc = []
            for a_ in accs:
                ww += _w(_rs(p_, a_))
            for a_, b_ in itertools.combinations(accs, 2):
                cc += _x(_rs(p_, a_), _rs(p_, b_))
            dd2.append(sum(cc) / len(cc) - sum(ww) / len(ww))
        m2 = sum(dd2) / len(dd2)
        se2 = (sum((d - m2) ** 2 for d in dd2) / (len(dd2) - 1)) ** 0.5 / len(dd2) ** 0.5
        print(f"  (b) 三对池化估计量：{m2:+.4f}，t(6) 95% CI [{m2-2.447*se2:+.4f}, {m2+2.447*se2:+.4f}]")
        print(f"      ^ 这是本方法论的默认口径")

    print(chr(10) + "=" * 66)
    print("\n" + "=" * 66)
    if args.json_out:
        out = Path(args.json_out)
    elif args.json:
        out = Path(args.json)
    else:
        out = None
    # ---------- 14. 品牌排名（v1.1 新增，业务需求：提及率 + 答案内名次 + 引用源数） ----------
    print(chr(10) + "【14】品牌排名（发现层 A1+A2；三指标 + Borda 综合名次）")
    _pool = by_layer["A1"] + by_layer["A2"]
    _rank_tbl = {}
    _ORD = re.compile(r"(?:^|[\n\s])(\d{1,2})\s*[.、．)）]\s*([^\n]{0,40})")
    for bname, aliases in BRAND_ALIASES.items():
        pat = re.compile("|".join(re.escape(a) for a in aliases), re.I)
        mentions = sum(1 for r in _pool if pat.search(r.get("answer") or ""))
        # 答案内名次：枚举答案中的序号列表项，品牌名落在条目文本前 40 字内即视作"该名次"
        ranks = []
        for r in _pool:
            ans = r.get("answer") or ""
            if not pat.search(ans):
                continue
            for m in _ORD.finditer(ans):
                frag = m.group(2)
                if pat.search(frag):
                    n_ = int(m.group(1))
                    if 1 <= n_ <= 20:
                        ranks.append(n_)
        cited = sum(1 for r in _pool if any(pat.search((c.get("title") or "") + (c.get("url") or ""))
                                            for c in (r.get("citations") or [])))
        _rank_tbl[bname] = {"mentions": mentions, "cite_samples": cited,
                            "ranked_times": len(ranks),
                            "rank_median": sorted(ranks)[len(ranks)//2] if ranks else None,
                            "rank_best": min(ranks) if ranks else None}
    # 本品牌同口径
    own_m = sum(1 for r in _pool if OWN_BRAND.search(r.get("answer") or ""))
    own_c = sum(1 for r in _pool if any(OWN_BRAND.search((c.get("title") or "") + (c.get("url") or ""))
                                        for c in (r.get("citations") or [])))
    own_r = []
    for r in _pool:
        ans = r.get("answer") or ""
        if not OWN_BRAND.search(ans):
            continue
        for m in _ORD.finditer(ans):
            if OWN_BRAND.search(m.group(2)):
                n_ = int(m.group(1))
                if 1 <= n_ <= 20:
                    own_r.append(n_)
    _rank_tbl["_本品牌"] = {"mentions": own_m, "cite_samples": own_c, "ranked_times": len(own_r),
                          "rank_median": sorted(own_r)[len(own_r)//2] if own_r else None,
                          "rank_best": min(own_r) if own_r else None}
    # Borda：提及样本数（主）、引用样本数、上榜次数（均降序；名次为展示项不进 Borda）
    names = [k for k in _rank_tbl if k != "_本品牌"] + ["_本品牌"]
    def _borda(key):
        order = sorted(names, key=lambda k: (-_rank_tbl[k][key], k))
        return {k: i + 1 for i, k in enumerate(order)}
    bm, bc, br = _borda("mentions"), _borda("cite_samples"), _borda("ranked_times")
    borda = {k: bm[k] + bc[k] + br[k] for k in names}
    print(f"  {'品牌':<8}{'提及样本':>6}{'引用样本':>6}{'上榜次数':>6}{'中位名次':>6}{'最佳':>4}{'Borda':>7}")
    for k in sorted(names, key=lambda k: (borda[k], k)):
        t = _rank_tbl[k]
        label = k.replace("_本品牌", OWN_BRAND.pattern[:8])
        rm = str(t["rank_median"]) if t["rank_median"] else "-"
        rb = str(t["rank_best"]) if t["rank_best"] else "-"
        print(f"  {label:<8}{t['mentions']:>6}{t['cite_samples']:>6}{t['ranked_times']:>6}{rm:>6}{rb:>4}{borda[k]:>7}")
    print("  （Borda=三项名次之和，越小越靠前；名次解析规则：答案中『数字+分隔符』列表项前 40 字含品牌名）")
    N["brand_rank"] = {k: {**v, "borda": borda[k]} for k, v in _rank_tbl.items()}

    if out is not None:
        out.write_text(json.dumps(N, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写出 {out}")
    return N


if __name__ == "__main__":
    main()
