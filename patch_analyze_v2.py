# -*- coding: utf-8 -*-
"""跨类目残留修复补丁 v2：逐项替换，报告每项结果"""
import sys
from pathlib import Path

f = Path("analyze_final.py")
src = f.read_text(encoding="utf-8")
n_ok = 0

def rep(tag, old, new):
    global src, n_ok
    if src.count(old) == 1:
        src = src.replace(old, new)
        n_ok += 1
        print(f"  [OK] {tag}")
    else:
        print(f"  [FAIL {src.count(old)}] {tag}")
        sys.exit(1)

# a) §6 本品牌标签参数化
rep("a-brand-label",
    '    print(f"  ★ 本品牌(斐驰/Fetrex) title∪url 命中 = {own}  ← 来源层")',
    '    print(f"  ★ 本品牌({OWN_BRAND.pattern}) title∪url 命中 = {own}  ← 来源层")')

# b) §7 ρ 保护
rep("b-rho-guard",
    '    print(f"  设计效应 DE = 1+4ρ = {1+4*pt:.2f}，CI [{1+4*blo:.2f}, {1+4*bhi:.2f}]\")\n'
    '    print(f"  → 重复的实际价值 = [{1/(1+4*bhi):.2f}x, {1/(1+4*blo):.2f}x]（跨过 1.0 = 可能无增益）")',
    '    de_lo, de_hi = 1 + 4 * blo, 1 + 4 * bhi\n'
    '    rho_estimable = len(five) >= 10 and de_lo > 0\n'
    '    print(f"  设计效应 DE = 1+4ρ = {1+4*pt:.2f}，CI [{de_lo:.2f}, {de_hi:.2f}]")\n'
    '    if rho_estimable:\n'
    '        print(f"  → 重复的实际价值 = [{1/de_hi:.2f}x, {1/de_lo:.2f}x]（跨过 1.0 = 可能无增益）")\n'
    '    else:\n'
    '        why = f"5 遍题仅 {len(five)} 条（<10）" if len(five) < 10 else "ρ CI 下界使 DE≤0"\n'
    '        print(f"  ⚠ ρ 的预算口径不可估：{why}。两阶段设计下 5 遍数据只来自摇摆题（选择偏差，")\n'
    '        print(f"    天然压负值——即 v1.0 美容仪教训的自动化重演）。预算请用 DE 敏感性双口径（§9）。")\n'
    '    N["rho_estimable"] = rho_estimable')

# c) §9 MDE 双口径
rep("c-mde-dual",
    '    print("  【单样本】与固定基线比较")\n'
    '    single = {}\n'
    '    RUNS = 5\n'
    '    for mde in (0.03, 0.05, 0.08, 0.10, 0.15):\n'
    '        n = math.ceil(z**2 * p * (1 - p) / mde**2)\n'
    '        # 有效独立样本 = m×runs / DE  →  m = n × DE / runs\n'
    '        m_prompts = math.ceil(n * (1 + 4 * pt) / RUNS)\n'
    '        single[f"{mde*100:.0f}pp"] = n\n'
    '        single[f"{mde*100:.0f}pp_prompts"] = m_prompts\n'
    '        print(f"    δ={mde*100:5.0f}pp → 需 {n:4d} 个独立样本 → 提示词 {m_prompts:3d} 条（每词{RUNS}遍，DE={1+4*pt:.2f}）")',
    '    print("  【单样本】与固定基线比较")\n'
    '    single = {}\n'
    '    RUNS = 5\n'
    '    if N.get("rho_estimable", True):\n'
    '        de_list = [(1 + 4 * pt, f"DE={1+4*pt:.2f}（ρ实测）")]\n'
    '    else:\n'
    '        de_list = [(1.0, "DE=1.0（下限）"), (1.5, "DE=1.5（敏感）")]\n'
    '        print("  （ρ 不可估 → DE 敏感性双口径）")\n'
    '    for mde in (0.03, 0.05, 0.08, 0.10, 0.15):\n'
    '        n = math.ceil(z**2 * p * (1 - p) / mde**2)\n'
    '        single[f"{mde*100:.0f}pp"] = n\n'
    '        parts = []\n'
    '        for de, tag in de_list:\n'
    '            m_prompts = math.ceil(n * de / RUNS)\n'
    '            parts.append(f"{m_prompts:3d} 条（{tag}）")\n'
    '            single[f"{mde*100:.0f}pp_prompts_de{de:.2f}"] = m_prompts\n'
    '        print(f"    δ={mde*100:5.0f}pp → 需 {n:4d} 个独立样本 → 提示词 " + " / ".join(parts))')

# d) §8/§13 账号对照数据源守卫
rep("d-acc-path",
    '    ca_path = ROOT / "data" / "compare_accounts.jsonl"\n'
    '    if ca_path.exists():\n'
    '        ca = read_jsonl(ca_path)',
    '    ca_path = Path(args.compare_data) if args.compare_data else (ROOT / "data" / "compare_accounts.jsonl")\n'
    '    ca = read_jsonl(ca_path) if ca_path.exists() else []\n'
    '    if ca:\n'
    '        _hit = {r["prompt_id"] for r in ca if r.get("account")} & {r["prompt_id"] for r in rows}\n'
    '        if not _hit:\n'
    '            print(f"  ⚠ 账号对照文件与当前数据 prompt_id 无交集（跨类目文件）——本节跳过")\n'
    '            ca = []\n'
    '    if ca:')
rep("d-acc-if",
    '    if ca_path.exists() and N.get("account_prompts"):',
    '    if ca and N.get("account_prompts"):')

# e) argparse --compare-data
rep("e-arg",
    '    ap.add_argument("--json-out", dest="json_out", default="", help="json 落盘路径（覆盖 --json 默认）")',
    '    ap.add_argument("--json-out", dest="json_out", default="", help="json 落盘路径（覆盖 --json 默认）")\n'
    '    ap.add_argument("--compare-data", default="", help="账号对照数据文件；与当前数据 pid 无交集时自动跳过该节")')

f.write_text(src, encoding="utf-8")
print(f"all {n_ok} patches applied")
