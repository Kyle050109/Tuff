#!/usr/bin/env bash
# regress.sh · 一条命令复算 T0 全部数字，并与冻结存档逐行比对
# 用法：bash regress.sh        （在 geo-lab 根目录）
# 通过条件：除「已知差异」外零 diff。已知差异（2026-10-20 登记）：
#   1) 「已写出 …」路径行（Windows/Mac/Linux 路径不同）
#   2) 美容仪 §账号对照节：data/compare_accounts.jsonl 不在仓库（原件在 Windows geo-lab）
#   3) 松胜/水裹「账号对照文件与当前数据题面不匹配」提示行（同上，文件缺失时不打印）
set -u
cd "$(dirname "$0")"
PY=${PY:-python3}
T0=archive/T0_2026-10-10
mkdir -p out
fail=0

run() { # name, archived, cmd...
  local name=$1 ref=$2; shift 2
  "$@" > "out/$name.txt" 2>&1 || { echo "✗ $name 运行失败"; fail=1; return; }
  local d
  d=$(diff <(sed 's/\r$//' "$ref" | grep -v '^已写出') <(grep -v '^已写出' "out/$name.txt"))
  if [ -z "$d" ]; then echo "✓ $name 与存档逐行一致"
  else
    if [ -f data/compare_accounts.jsonl ]; then echo "✗ $name 存在差异："; echo "$d" | head -30; fail=1
    else
      # 仅允许账号对照相关行缺失
      local bad
      bad=$(echo "$d" | grep '^[<>]' | grep -v -E '账号对照|完整题 7 条|组内均值|单值范围|跨−组|cluster 水平|配对估计量|第三方报的|三对池化|本方法论的默认口径')
      if [ -z "$bad" ]; then echo "✓ $name 一致（仅缺账号对照节：compare_accounts.jsonl 未入库）"
      else echo "✗ $name 存在非预期差异："; echo "$bad" | head -30; fail=1; fi
    fi
  fi
}

run beauty "$T0/final_v16_output.txt" $PY analyze_final.py
run chair  "$T0/chair_v1_output.txt"  $PY analyze_final.py --prompts prompts/anmo_chair_v1.json --data data/chair_samples.jsonl --json-out out/chair_numbers.json
run spa    "$T0/spa_v1_output.txt"    $PY analyze_final.py --prompts prompts/shenzhen_spa_v1.json --data data/spa_samples.jsonl --json-out out/spa_numbers.json
run ds_beauty "$T0/ds_beauty.txt" $PY ds_analyze.py --prompts prompts/meirongyi_final_v2.json --data data/deepseek/ds_beauty_baseline.jsonl
run ds_chair  "$T0/ds_chair.txt"  $PY ds_analyze.py --prompts prompts/anmo_chair_v1.json --data data/deepseek/ds_chair_baseline.jsonl
run ds_spa    "$T0/ds_spa.txt"    $PY ds_analyze.py --prompts prompts/shenzhen_spa_v1.json --data data/deepseek/ds_spa_baseline.jsonl

echo "── 数据完整性（md5）"
md5sum -c --quiet MANIFEST_T0.md5 && echo "✓ T0 数据/题库 md5 全部一致" || fail=1
exit $fail
