# -*- coding: utf-8 -*-
"""跨类目修复补丁 v3：json 写盘缩进、§10 标题、§11 face_hits、§8 守卫升级（text 匹配）"""
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

# 1) json 写盘缩进（--json-out 分支只赋值不写盘的 bug）
rep("json-write",
    '''        out = Path(args.json_out)
    elif args.json:
        out = Path(args.json)
        out.write_text(json.dumps(N, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写出 {out}")
    return N''',
    '''        out = Path(args.json_out)
    elif args.json:
        out = Path(args.json)
    else:
        out = None
    if out is not None:
        out.write_text(json.dumps(N, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写出 {out}")
    return N''')

# 2) §10 标题的"7 次"参数化（打印挪到循环内取 k 后重写该行）
rep("sec10-title",
    '''    print(chr(10) + "【10】超几何：7 次提及全落在触发检索样本内的概率（两池并列，基线口径用 A1）")''',
    '''    print(chr(10) + "【10】超几何：全部提及都落在触发检索样本内的概率（两池并列，基线口径用 A1）")''')

# 3) §11 face_hits 用当前 BRAND_ALIASES 键（美容仪硬编码列表 → 跨类目空括号）
rep("face-hits",
    '''    face_hits = {b: sum(1 for t in a2face.values() if b in t)
                 for b in ["雅萌", "觅光", "初普", "极萌", "宙斯", "大排灯"]}''',
    '''    _face_brands = [a for b in BRAND_ALIASES.values() for a in b]   # v1.6 残留：旧版硬编码美容仪品牌
    face_hits = {b: sum(1 for t in a2face.values() if b in t) for b in _face_brands}''')

# 4) §8 守卫升级：pid 撞名不够，必须 text 匹配（B01 美容仪 vs B01 按摩椅）
rep("guard-text",
    '''        _hit = {r["prompt_id"] for r in ca if r.get("account")} & {r["prompt_id"] for r in rows}
        if not _hit:
            print(f"  ⚠ 账号对照文件与当前数据 prompt_id 无交集（跨类目文件）——本节跳过")
            ca = []''',
    '''        # 守卫两道：pid 交集 + 题面 text 匹配（跨类目会撞 pid 前缀，如 B01 美容仪 vs B01 按摩椅）
        _texts_now = {r["text"] for r in rows}
        _hit = sum(1 for r in ca if r.get("account") and r.get("text") in _texts_now)
        _tot = sum(1 for r in ca if r.get("account"))
        if _hit < _tot * 0.8:
            print(f"  ⚠ 账号对照文件与当前数据题面不匹配（{_hit}/{_tot} 条 text 命中——跨类目文件），本节跳过")
            ca = []''')

f.write_text(src, encoding="utf-8")
print("all patches applied")
