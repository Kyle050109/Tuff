# geo-lab · GEO 答案层测量代码库

单一可信源：所有对外数字只能由本仓库脚本产出（方法论 §十二.10、§十三）。

## 目录

| 路径 | 内容 |
|---|---|
| `analyze_final.py` | 豆包答案层分析器（算法 1–14），题库 meta 驱动 |
| `ds_analyze.py` | DeepSeek Search API 来源层分析（2026-10-20 新建） |
| `geolib.py` | JSONL 安全读写 / 去重 |
| `run_samples.py` | 豆包采集器（浏览器自动化） |
| `ds_geoscout.py` | DeepSeek Search API 采集器（需 `DEEPSEEK_API_KEY`） |
| `permutation_test.py` | 账号不变性置换检验（需 `data/compare_accounts.jsonl`） |
| `verify_*.py` / `evidence_check.py` / `stage2_plan.py` | 复核与两阶段规划脚本 |
| `patch_analyze_v2-4.py` | 历史跨类目补丁（已并入 analyze_final.py，仅留档） |
| `prompts/` | 三个类目题库（meta 含品牌表、layer_assert） |
| `data/` | 豆包采集原始数据；`data/deepseek/` 为 Search API 原始数据 |
| `archive/T0_2026-10-10/` | **T0 冻结基线**：分析输出存档 + 采集日志（只读） |
| `MANIFEST_T0.md5` | T0 数据与题库 md5 |
| `regress.sh` | 一条命令复算全部数字（T0 口径 + alias v2 口径，共 18 项，含置换检验）并与存档比对 |
| `alias_scan.py` | 别名漏命中扫描（繁体），新增品牌时必跑 |
| `OBJECT_SPEC.md` | 测量对象说明（一页纸） |
| `RETRACTIONS.md` | 撤回与更正记录 |
| `FOLLOWUP_交接人.md` | 需向交接人跟进的事项 |
| `prompts/*_v2.json`、`meirongyi_v3.json` | **当前生效题库**（补繁体别名；水裹补 layer_assert）。T0 原题库冻结 |

## 文件名对照（原始数据包 ↔ 仓库）

| 原始数据包 03_原始数据 | 仓库 |
|---|---|
| 题库/美容仪_114条.json | prompts/meirongyi_final_v2.json |
| 题库/按摩椅_104条.json | prompts/anmo_chair_v1.json |
| 题库/汤泉_100条.json | prompts/shenzhen_spa_v1.json |
| 豆包/美容仪_samples.jsonl | data/samples.jsonl（分析器默认模式路径） |
| 豆包/按摩椅_samples.jsonl | data/chair_samples.jsonl |
| 豆包/水裹_samples.jsonl | data/spa_samples.jsonl |
| DeepSeek/{美容仪,按摩椅,水裹}_search_results.jsonl | data/deepseek/ds_{beauty,chair,spa}_baseline.jsonl |

## 复算

```bash
bash regress.sh            # 期望：6 项 ✓ + md5 ✓
```

## 版本

- `analyze_final.py` 以 03/06 包版本（v6，md5 a9dc2d2d…）为准；04 包旧版（v5，33898b1d…）已被其完全覆盖，不再使用。
- `data/compare_accounts.jsonl`、`data/accounts.json`：2026-10-21 第二批数据补入，regress 已是严格逐行比对。
- `archive/received_2026-10-21/`：第二批数据中交接人提供的分析结果原件（ds_cross_analysis.json 等），只读留档。
