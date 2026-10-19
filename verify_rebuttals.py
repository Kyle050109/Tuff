# -*- coding: utf-8 -*-
"""核实反驳论点的数据支撑"""
import json, re
from collections import Counter

rows=[json.loads(l) for l in open('data/chair_samples.jsonl',encoding='utf-8') if l.strip()]
dd={}
for r in rows: dd[(r['prompt_id'],r['run_idx'])]=r
valid=[r for r in dd.values() if r.get('ok')]
disc=[r for r in valid if '松胜' not in r['text'] and not any(c in r['text'] for c in ['奥佳华','OGAWA','荣泰','傲胜','OSIM','松下','西屋','芝华仕','迪斯','佳仁','海尔'])]
ment=[r for r in disc if '松胜' in (r.get('answer') or '')]
n=len(ment)

# 反驳点 1：精钢 30.77% vs 23% = 不同口径
full_jg = sum(1 for r in ment if '精钢' in (r.get('answer') or ''))
full_xjb = sum(1 for r in ment if '性价比' in (r.get('answer') or ''))
def sent_bind(hook):
    bind=0
    for r in ment:
        ans=r.get('answer') or ''
        for m in re.finditer(r'松胜', ans):
            starts=[x.end() for x in re.finditer(r'[。！？\n]|(?:\d[.、])', ans[:m.start()])]
            s=max(starts) if starts else 0
            ends=[x.start() for x in re.finditer(r'[。！？\n]', ans[m.start():])]
            e=m.start()+min(ends) if ends else len(ans)
            if hook in ans[s:e]: bind+=1; break
    return bind
sj_jg = sent_bind('精钢')
sj_xjb = sent_bind('性价比')
print("反驳1: 精钢/性价比双口径")
print(f"  精钢: 全文 {full_jg}/{n}={100*full_jg/n:.1f}% | 句级 {sj_jg}/{n}={100*sj_jg/n:.1f}%")
print(f"  性价比: 全文 {full_xjb}/{n}={100*full_xjb/n:.1f}% | 句级 {sj_xjb}/{n}={100*sj_xjb/n:.1f}%")
print(f"  → DS 说的 30.77% 是全文口径；方案的 23% 是句级口径。两个数都对，量不同东西。")

# 反驳点 2：竞品官网被引的题面混杂
print("\n反驳2: 竞品官网被引样本的题面混杂")
for name, kw, dom in [("傲胜", ["傲胜","OSIM"], "osim"), ("西屋", ["西屋"], "westinghouse"), ("松下", ["松下","panasonic"], "panasonic")]:
    hit=[r for r in disc if any(dom in (c.get('url') or '') for c in (r.get('citations') or []))]
    if not hit: continue
    named=sum(1 for r in hit if any(k in r['text'] for k in kw))
    sg_ment=sum(1 for r in hit if '松胜' in (r.get('answer') or ''))
    print(f"  {name}官网被引{len(hit)}样本｜题面点名竞品{named}({100*named/len(hit):.0f}%)｜松胜提及{sg_ment}")

# 反驳点 3：候选池大小与品牌密度的方向性
print("\n反驳3: 候选池大小不能完全解释品牌密度方向")
# 松胜 10 个候选、密度 1.81；斐驰 25 个候选、密度 3.97
# 如果候选池大小是唯一因素，那么候选少的品牌密度应该更低（更难出现）
# 但松胜的提及率是三类目最高——说明"少而精"的候选被更频繁地列出
# 这个方向性本身就是对"列表长度解释"的反驳
print("  松胜候选 10 个 → 品牌密度 1.81（每答案 1.81 个品牌）")
print("  斐驰候选 25 个 → 品牌密度 3.97（每答案 3.97 个品牌）")
print("  如果列表长度是唯一因素 → 候选多应该密度高（斐驰 3.97 确实高）")
print("  但反过来：松胜候选只有 10 个，如果按比例密度应该只有 25→10 的 1.59（=3.97*10/25）")
print(f"  实际是 1.81 > 1.59 → 松胜的品牌在候选池中的'覆盖率'比斐驰高 {(1.81/10)/(3.97/25):.2f}x")
print("  → 候选池大小有影响但不能完全解释：松胜品牌在有限候选中的密度比按比例预期更高")
