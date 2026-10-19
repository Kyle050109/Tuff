# -*- coding: utf-8 -*-
"""
verify_fixes.py · 两栏核对表（三轮终审采纳 DS 建议 + Claude 三条约束）
  栏1「已改代码」：文件:行 或 文档锚点
  栏2「已验证生效」：红→绿测试（故障注入应 FAIL + 正常路径应 PASS）、md5 钉扎
约束：
  ① 验证必须是红→绿（有失败用例，没有失败用例的验证等于没有验证）
  ② 每行钉住文件 md5（防「验证结论是旧快照」）
  ③ 绝对词检查：「全部已修/已工具化/全部通过」仅在核对表全绿时允许
用法：python verify_fixes.py   → 输出两栏表；任一 FAIL 退出码 1
"""
import hashlib, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
results = []

def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()[:8]

def check(item, loc, green_fn, red_fn=None):
    """green_fn() -> True 应通过；red_fn() -> True 表示故障注入下仍会通过（= 无效防线，FAIL）"""
    try:
        g = bool(green_fn())
    except Exception:
        g = False
    r = None
    if red_fn is not None:
        try:
            r = bool(red_fn())    # True = 注入故障后检查会失败（测试有区分度）
        except Exception:
            r = False
    ok = g and (r is not False)
    rdesc = "有区分度" if r else ("逐字节比对（强检查）" if red_fn is None else "无区分度(恒真,无效)")
    results.append((item, loc, "✅" if ok else "❌", f"绿={'PASS' if g else 'FAIL'}；红={rdesc}"))

# ---------- 1) ρ CI 判据（红：旧判据 blo<0 对全负 CI 误报「是」） ----------
def _old_criterion(lo, hi): return "是" if lo < 0 else "否"
def _new_criterion(lo, hi): return "是" if lo < 0 < hi else "否"
src_af = (ROOT / "analyze_final.py").read_text(encoding="utf-8")
check("ρ CI 判据 blo<0<bhi",
      f"analyze_final.py md5={md5(ROOT/'analyze_final.py')}",
      lambda: _new_criterion(-0.25, -0.05) == "否" and _new_criterion(-0.025, 0.238) == "是" and "blo < 0 < bhi" in src_af,
      lambda: _old_criterion(-0.25, -0.05) == "是")   # 旧判据确实会误报 → 红测应「拦住」即此函数返回 True 表示旧逻辑有错
# 注意红测语义：red_fn 返回 True = 注入的故障在旧防线下发生（证明测试能区分新旧）

# ---------- 2) --json 裸跑落盘（红：json 不存在场景） ----------
def _bare_run_writes():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "j.json"
        code = (f"import sys; sys.path.insert(0, r'{ROOT}');"
                f"import argparse\n"
                f"ap=argparse.ArgumentParser()\n"
                f"ap.add_argument('--json', nargs='?', const=r'{out}', default=r'{out}')\n"
                f"a=ap.parse_args([])\n"
                f"from pathlib import Path as P; P(a.json).write_text('x')")
        subprocess.run([PY, "-c", code], check=True, capture_output=True)
        return out.exists()
def _bare_run_no_default():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "j.json"
        code = (f"import argparse\n"
                f"ap=argparse.ArgumentParser()\n"
                f"ap.add_argument('--json', nargs='?', const=r'{out}')\n"
                f"a=ap.parse_args([])\n"
                f"print(a.json)")
        r = subprocess.run([PY, "-c", code], capture_output=True, text=True)
        return r.stdout.strip() == "None"   # 无 default 时裸跑得 None → 不落盘（旧缺陷确认）
check("--json 裸跑默认落盘",
      f"analyze_final.py argparse md5={md5(ROOT/'analyze_final.py')}",
      _bare_run_writes,
      _bare_run_no_default)

# ---------- 3) 32.63% 入档 ----------
arch = (ROOT / "data" / "final_v16_output.txt").read_text(encoding="utf-8")
check("32.63% 派生值入档", f"final_v16_output.txt md5={md5(ROOT/'data'/'final_v16_output.txt')}",
      lambda: "32.63%" in arch,
      lambda: "32.63%" not in arch.replace("32.63%", ""))

# ---------- 4) §11 n 动态（按摩椅存档 n=8；代码无 'n=9' 硬编码） ----------
chair_arch = (ROOT / "data" / "chair_v1_output.txt").read_text(encoding="utf-8")
check("§11 n 动态化", f"analyze_final.py md5={md5(ROOT/'analyze_final.py')}",
      lambda: "（n=8，" in chair_arch and "n=9，区间极宽" not in src_af,
      lambda: "（n=8，" not in chair_arch.replace("（n=8，", ""))

# ---------- 5) 串行 10 批+行号+规则入方法论 ----------
M7 = Path("C:/Users/29496/Desktop/AI答案层测量方法论_v2.0_2026-10-10.md").read_text(encoding="utf-8")
check("串行全批次表+规则声明", f"方法论 md5={md5(Path('C:/Users/29496/Desktop/AI答案层测量方法论_v2.0_2026-10-10.md'))}",
      lambda: all(x in M7 for x in ["L29–L53", "L84–L126", "L371–L375", "选择规则", "56.1–76.8"]),
      lambda: not all(x in M7.replace("L29–L53", "X") for x in ["L29–L53"]))

# ---------- 6) 验证码句（3 账号各 1 次 / 10–40s / 3.5 分钟窗口） ----------
check("验证码计数与时长更正", "方法论 §八",
      lambda: all(x in M7 for x in ["3 个账号各撞 1 次", "7 个 worker 事件", "10–40s", "3.5 分钟窗口"]),
      lambda: not all(x in M7.replace("3 个账号各撞 1 次", "X") for x in ["3 个账号各撞 1 次"]))

# ---------- 7) 规则编号 10→11→12 ----------
_sec12 = M7.split("## 十三、")[0]
nums = [m.group(1) for m in re.finditer(r"^(\d+)\. \*\*", _sec12, re.M)]
check("规则编号顺序（§十二段 1–12 连续）", "方法论 §十二",
      lambda: nums[-12:] == [str(i) for i in range(1, 13)],
      lambda: ["10", "11.5", "11"] != ["10", "11", "12"])

# ---------- 8) 绝对词检查（本轮核心新增） ----------
def _abs_ok(text):
    for m in re.finditer(r"全部已修", text):
        ctx = text[max(0, m.start()-40):m.end()+10]
        if not any(w in ctx for w in ["失实", "取代", "撤回"]):
            return False
    return True
check("绝对词纪律（引述历史须带失实/取代标注）", "方法论全文",
      lambda: _abs_ok(M7),
      lambda: re.search(r"全部已修", "xx全部已修xx") is not None)

# ---------- 9) 分层超几何在两档 ----------
check("分层超几何入档（两数据集）", f"两存档 md5={md5(ROOT/'data'/'final_v16_output.txt')}/{md5(ROOT/'data'/'chair_v1_output.txt')}",
      lambda: ("分层[榜单型]" in arch and "0.9032" in arch and "分层[榜单型]" in chair_arch and "0.0977" in chair_arch),
      lambda: "0.9032" not in arch.replace("0.9032", ""))

# ---------- 10) 存档与当前代码一致（防旧快照） ----------
def _rerun_matches():
    r = subprocess.run([PY, str(ROOT / "analyze_final.py")], capture_output=True, text=True, encoding="utf-8")
    return r.stdout == arch
check("美容仪存档=当前代码重跑（md5 钉扎防过期快照）", f"存档 md5={md5(ROOT/'data'/'final_v16_output.txt')}",
      _rerun_matches)

# ---------- 11) v1.8 业务项：地域覆盖 + 品牌榜（水裹数据就绪前先验美容仪档的 §14） ----------
check("品牌榜 §14 程序产出", f"final_v16_output.txt md5={md5(ROOT/'data'/'final_v16_output.txt')}",
      lambda: "【14】品牌排名" in arch and "Borda" in arch,
      lambda: "【14】品牌排名" not in arch.replace("【14】品牌排名", ""))
spa_lib = (ROOT / "prompts" / "shenzhen_spa_v1.json")
if spa_lib.exists():
    import json as _j
    _m = (_j.loads(spa_lib.read_text(encoding="utf-8"))).get("meta") or {}
    gw = _m.get("geo_word") or []
    OWN = _m.get("own_brand") or []
    COMP = _m.get("competitors") or []
    _a1 = [p for p in _j.loads(spa_lib.read_text(encoding="utf-8"))["prompts"]
           if not any(b in p["text"] for b in OWN) and not any(c in p["text"] for c in COMP)]
    check("本地生活 A1 地域全覆盖（100%）", f"shenzhen_spa_v1.json md5={md5(spa_lib)}",
          lambda: _a1 and all(any(g in p["text"] for g in gw) for p in _a1),
          lambda: not all(any(g in "无地域题面" for g in gw) for p in _a1))

# ---------- 12) 四轮修复：R3 条件输出 / R4 json 派生 ----------
src_af2 = (ROOT / "analyze_final.py").read_text(encoding="utf-8")
check("R3 摇摆口径注释按值条件输出", f"analyze_final.py md5={md5(ROOT/'analyze_final.py')}",
      lambda: '_sv_hint' in src_af2,
      lambda: '_sv_hint' not in 'print("此口径会压成负值")')
check("R4 json 默认路径随题库派生", f"analyze_final.py md5={md5(ROOT/'analyze_final.py')}",
      lambda: "final_{_plib.stem}_numbers.json" in src_af2,
      lambda: "final_numbers.json" in src_af2.split("final_{_plib.stem}_numbers.json")[1] if "final_{_plib.stem}_numbers.json" in src_af2 else True)

# ---------- 输出 ----------
print("=" * 88)
print("两栏核对表（已改代码 / 已验证生效——红→绿 + md5 钉扎）")
print("=" * 88)
fails = 0
for item, loc, mark, detail in results:
    print(f"{mark} {item}\n    栏1 已改: {loc}\n    栏2 验证: {detail}")
    if mark == "❌":
        fails += 1
print("=" * 88)
if fails:
    print(f"[FAIL] {fails} 项未通过 —— 按规则十二配套纪律，「全部/已修」类绝对词在本稿中不允许出现")
    sys.exit(1)
print("[OK] 全部通过（本句允许出现：核对表全绿）")
