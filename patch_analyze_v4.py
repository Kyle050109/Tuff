# -*- coding: utf-8 -*-
"""补丁 v4：DS 应改项5 + Claude 补充——把无档数字全部补进 stdout 存档
意图触发率两池表 / ρ 子集提及率 / 字节系全层 / 榜单型占比 / 未触发上界 / 域名两池对照"""
import sys
from pathlib import Path

f = Path("analyze_final.py")
src = f.read_text(encoding="utf-8")

def rep(tag, old, new):
    global src
    if src.count(old) == 1:
        src = src.replace(old, new); print(f"  [OK] {tag}")
    else:
        print(f"  [FAIL {src.count(old)}] {tag}"); sys.exit(1)

# 1) 未触发上界进 stdout（§4 内，现仅落 json）
rep("nontrig-stdout",
    '''        N[f"nontrig_upper_{tag}"] = cp_upper(0, len(nst))''',
    '''        _up = cp_upper(0, len(nst), 0.025)
        N[f"nontrig_upper_{tag}"] = _up
        if nst:
            print(f"    {tag} 未触发 0/{len(nst)} 双侧95%上界 ≤ {_up:.2f}%")''')

# 2) 意图触发率两池表 + 榜单占比 + 字节系全层 + 域名两池对照，追加为 §4b
rep("sec4b",
    '''    # ---------- 5. 引用域 ----------''',
    '''    # ---------- 4b. 意图触发率（两池并列，防混池）+ 构成占比 ----------
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
                  f"｜样本口径(A1+A2) {sum(1 for r in A1+A2 if r['intent']==name)}/{len(A1+A2)}")
    N["intent_prompt_counts"] = dict(_ic)

    # ---------- 5. 引用域 ----------''')

# 3) §5 增加两池域名对照（防 N1 类混池）与字节系全层
rep("sec5-pools",
    '''    print(f"  至少含 1 条抖音的样本 {withdy}/{len(A)}")''',
    '''    print(f"  至少含 1 条抖音的样本 {sum(1 for r in A if 'iesdouyin.com' in (r.get('citation_hosts') or []))}/{len(A)}")
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
    N["ya_man_family"] = [_ya1, _ya2]''')

# 4) ρ 子集提及率（§7 内补打印）
rep("rho-subset",
    '''    # 对照：只用摇摆题（错误口径）''',
    '''    _m5 = [k for k in five]
    _m1 = [k for k in byp if len(byp[k]) == 1]
    if _m5 and _m1:
        r5 = sum(1 for k in _m5 for v in five[k] if v) / sum(len(five[k]) for k in _m5)
        r1 = sum(1 for k in _m1 for v in byp[k] if v) / sum(len(byp[k]) for k in _m1)
        print(f"  子集提及率：5 遍题 {sum(1 for k in _m5 for v in five[k] if v)}/{sum(len(five[k]) for k in _m5)}"
              f" = {100*r5:.2f}%｜单遍题 {sum(1 for k in _m1 for v in byp[k] if v)}/{sum(len(byp[k]) for k in _m1)}"
              f" = {100*r1:.2f}%（A1+A2 池）")
        N["rho_subset_rates"] = [100*r5, 100*r1]

    # 对照：只用摇摆题（错误口径）''')

f.write_text(src, encoding="utf-8")
print("all patches applied")
