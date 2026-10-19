# -*- coding: utf-8 -*-
"""第二阶段判定（v2 修正）：题级跨账号池化；v1.1 参数化 --data（默认按摩椅文件）。"""
import json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from geolib import read_jsonl, dedupe_last

import argparse as _ap
_a = _ap.ArgumentParser(); _a.add_argument("--data", default="data/chair_samples.jsonl"); _a.add_argument("--out-ids", default="data/stage2_ids.txt")
_args = _a.parse_args()
raw = read_jsonl(Path(_args.data))
rows = dedupe_last(raw)
ok = [r for r in rows if r.get("ok")]

# 题级：pid -> run_idx -> [mentioned,...]（去重后每 (pid,run) 至多一条；按账号去重时
# 用 (pid, run, account) 键才不会互相覆盖——先按全键收集再池化）
by = defaultdict(lambda: defaultdict(list))
for r in ok:
    by[r["prompt_id"]][r["run_idx"]].append(bool(r.get("brand_mentioned")))

allpids = sorted({r["prompt_id"] for r in raw})
inconsistent, missing = set(), set()
for pid in allpids:
    runs = by.get(pid, {})
    if not (1 in runs and 2 in runs):
        missing.add(pid)                      # 题级缺某遍（采集失败/未覆盖）
    elif any(runs[1]) != any(runs[2]):
        inconsistent.add(pid)                 # 两遍提及不一致 → 摇摆候选

print(f"题 {len(allpids)} 条｜有效 (pid,run) 对 {sum(len(v) for v in by.values())}")
print(f"两遍不一致（摇摆候选，{len(inconsistent)} 条）：{sorted(inconsistent)}")
print(f"题级缺遍（{len(missing)} 条）：{sorted(missing)}")
ids = sorted(set(inconsistent) | set(missing))
Path(_args.out_ids).write_text(",".join(ids), encoding="utf-8")
print(f"第二阶段 ids → data/stage2_ids.txt（{len(ids)} 条，加跑 run3-5）")
