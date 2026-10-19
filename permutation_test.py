# -*- coding: utf-8 -*-
"""
账号不变性检验 · 可复跑版 v2
======================================================
v1 的置换检验是**退化的**（第三方复核指出，本文件已修正）：

  统计量 = mean(跨号对) - mean(组内对)，题内交换两个账号标签时，
  组内对的并集与跨号对**都不变** -> 统计量恒等不变，
  200 次置换极差实测 0.0000000000。那个 p=1.0000 是构造值，不是检验结果。

v2 的两处根本修改：
 1. 置换「run 的归属」而不是「账号的标签」：把每条题的 9 个 run 池化后随机重分成
    3 组(3/3/3)，这样组内/跨号划分**真的会变**，统计量随之变化。
 2. 先做功效自检再报 p 值：用带已知账号效应的合成数据验证本检验能检出效应，
    通过后才报实测 p 值。一个检出不了已知效应的检验，不该产出对外数字。

用法：python permutation_test.py          # 完整
      python permutation_test.py --fast   # 少置换次数
"""
import sys, random, itertools, statistics as st
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geolib import read_jsonl

ROOT = Path(__file__).resolve().parent
SEED = 20261010
N_PERM = 2000


def jac(a, b):
    if not a and not b:
        return None
    return len(a & b) / len(a | b) if (a and b) else 0.0


def stat_from_groups(groups):
    within, cross = [], []
    for gi in groups:
        for x, y in itertools.combinations(gi, 2):
            v = jac(x, y)
            if v is not None:
                within.append(v)
    for i, j in itertools.combinations(range(len(groups)), 2):
        for x in groups[i]:
            for y in groups[j]:
                v = jac(x, y)
                if v is not None:
                    cross.append(v)
    if not within or not cross:
        return None
    return sum(cross) / len(cross) - sum(within) / len(within)


def load():
    ca = read_jsonl(ROOT / "data" / "compare_accounts.jsonl")
    g = defaultdict(lambda: defaultdict(dict))
    for r in ca:
        if r.get("account"):
            g[r["prompt_id"]][r["account"]][r["run_idx"]] = set(r.get("citation_hosts") or [])
    full = sorted(p for p, a in g.items()
                  if len(a) == 3 and all(len(v) == 3 for v in a.values()))
    return g, full


def perm_test(by_prompt, full, n_perm, rng):
    """by_prompt: {pid: [9 个 run 的 host 集合]}（顺序 = acc1x3, acc2x3, acc3x3）"""

    def stat(assign):
        diffs = []
        for pid in full:
            runs = by_prompt[pid]
            v = stat_from_groups([[runs[i] for i in grp] for grp in assign[pid]])
            if v is not None:
                diffs.append(v)
        return sum(diffs) / len(diffs) if diffs else None

    obs = stat({pid: [list(range(0, 3)), list(range(3, 6)), list(range(6, 9))] for pid in full})
    vals = []
    for _ in range(n_perm):
        assign = {}
        for pid in full:
            idx = list(range(9))
            rng.shuffle(idx)
            assign[pid] = [idx[0:3], idx[3:6], idx[6:9]]
        v = stat(assign)
        if v is not None:
            vals.append(v)
    cnt = sum(1 for v in vals if abs(v) >= abs(obs))
    return obs, (cnt + 1) / (len(vals) + 1), vals


def power_check(rng, n_perm, mix=2):
    """合成数据写入已知账号效应，看检验能否检出。

    mix = 混入异组域条数（12 域中）；take = 12-mix 为偏好域条数。
    mix 与效应量的对应关系**只能实测、不能推算**——主流程会打印实测扫描表
    （【功效自检·mix 扫描】一节），本 docstring 不再手写任何数字（v1.6 修正：
    此前手写的 -0.269/-0.066 等标注来自另一组种子，与实跑不符，已删）。
    """
    take = 12 - mix
    base_a = sorted({f"a{i}.com" for i in range(12)})
    base_b = sorted({f"b{i}.com" for i in range(12)})
    by_prompt = {}
    for pid in ["P1", "P2", "P3", "P4"]:
        runs = []
        for acct in range(3):
            for _ in range(3):
                if acct == 0:
                    runs.append(set(rng.sample(base_a, take)) | set(rng.sample(base_b, mix)))
                else:
                    runs.append(set(rng.sample(base_b, take)) | set(rng.sample(base_a, mix)))
        by_prompt[pid] = runs
    obs, p, _ = perm_test(by_prompt, list(by_prompt), n_perm, rng)
    return obs, p


def main():
    n_perm = 200 if "--fast" in sys.argv else N_PERM
    g, FULL = load()
    by_prompt = {p: [g[p][a][r] for a in sorted(g[p]) for r in sorted(g[p][a])] for p in FULL}

    print("=" * 64)
    print(f"数据集：{len(FULL)} 条题 x 3 账号 x 3 遍 = {len(FULL)*9} 个样本")
    print(f"置换设计：每条题的 9 个 run 池化后随机重分 3 组（组内/跨组划分真的会变）")
    print(f"置换次数：{n_perm}  种子：{SEED}")

    print("\n【功效自检·两档】合成数据写入已知账号效应，检验能否检出（v1.5 起分两档）")
    pc_nperm = min(n_perm, 400)
    print(f"  （自检用 {pc_nperm} 次置换 → p 最小分辨率 = 1/{pc_nperm+1} = {1/(pc_nperm+1):.4f}；"
          f"主检验用 {n_perm} 次 → {1/(n_perm+1):.4f}。两者分别标注）")
    ok = True
    print("  第 1 档·强效应（mix=2）：证明检验结构有效（观测差量级见下方试验输出）")
    for t in range(3):
        rng = random.Random(SEED + t)
        obs, p = power_check(rng, pc_nperm, mix=2)
        print(f"    试验{t+1}: 观测差 {obs:+.4f}  p = {p:.4f}  {'[OK] 检出' if p < 0.05 else '[FAIL] 未检出'}")
        if p >= 0.05:
            ok = False
    print("  第 2 档·阈值级效应（mix=4，目标量级 ≈ 本报告可排除阈值 0.079）：")
    det = 0; trials = 10; obs_list = []
    for t in range(trials):
        rng = random.Random(SEED + 100 + t)
        obs, p = power_check(rng, pc_nperm, mix=4)
        obs_list.append(obs); det += (p < 0.05)
    print(f"    实测：均值 {st.mean(obs_list):+.4f}，范围 [{min(obs_list):+.4f}, {max(obs_list):+.4f}]，"
          f"检出 {det}/{trials} —— "
          f"{'[OK] 阈值级效应大多可检出' if det >= 7 else '[注意] 对阈值级效应功效不足'}")
    print("    （该档决定「置换检验能否独立支撑 0.079 阈值」的表述；实测数据的阈值结论仍以 t(6) CI 为准）")
    print("  [OK] 功效自检通过：本检验能检出已知效应。" if ok
          else "  [!] 功效自检未全部通过 -- 本检验输出不可作为对外证据。")

    print("\n【功效自检·mix 扫描】效应量随 mix 的实测变化（v1.6 固化；"
          "此前「mix=6 ≈0」的教训只有过程叙述、无存档）")
    for m in (2, 3, 4, 5, 6):
        vals_m = []; det_m = 0; trials_m = 5
        for t in range(trials_m):
            rng = random.Random(SEED + 300 + t)
            obs_m, p_m = power_check(rng, pc_nperm, mix=m)
            vals_m.append(obs_m); det_m += (p_m < 0.05)
        print(f"    mix={m}: 观测差均值 {st.mean(vals_m):+.4f}，范围 [{min(vals_m):+.4f}, {max(vals_m):+.4f}]，"
              f"检出 {det_m}/{trials_m}")

    print("\n【实测】原假设：账号标签不携带信息（run 可跨账号互换）")
    rng = random.Random(SEED)
    obs, p, vals = perm_test(by_prompt, FULL, n_perm, rng)
    vs = sorted(vals)
    print(f"  观测统计量（逐题「跨-组」均值）= {obs:+.4f}")
    print(f"  置换分布：均值 {st.mean(vals):+.4f}，SD {st.stdev(vals):.4f}，"
          f"95% 区间 [{vs[int(.025*len(vs))]:+.4f}, {vs[int(.975*len(vs))]:+.4f}]")
    print(f"  **置换 p = {p:.4f}**（双侧）")
    print(f"  分辨率：{n_perm} 次置换下最小可达 p = {1/(n_perm+1):.4f}")

    print("\n【效应量】题为单位（cluster 水平）")
    diffs = [stat_from_groups([by_prompt[x][0:3], by_prompt[x][3:6], by_prompt[x][6:9]]) for x in FULL]
    diffs = [d for d in diffs if d is not None]
    m = st.mean(diffs)
    se = st.stdev(diffs) / len(diffs) ** 0.5
    tc = 2.447
    print(f"  逐题差值均值 = {m:+.4f}，SE {se:.4f}")
    print(f"  t({len(diffs)-1}) 95% CI [{m-tc*se:+.4f}, {m+tc*se:+.4f}]")
    print(f"  -> 可排除的平均差 > {max(abs(m-tc*se), abs(m+tc*se)):.3f}")

    print("\n【对照】v1 的退化检验（仅供对照，不可签发）")
    print("  v1 统计量在置换下恒为定值（实测极差 0.0），其 p=1.0000 是构造值。")
    print("  注意：v1 输出的观测值 +0.0064（acc1 vs acc2 配对）本身可复现，")
    print("        但它的 p 值不可用。两个估计量（配对 +0.0064 / 池化 -0.0032）应分别标注。")


if __name__ == "__main__":
    main()
