# 原始数据档案

## 目录结构

```
豆包/          ← 浏览器采集的 AI 回答原始数据（3 个类目）
DeepSeek/      ← DeepSeek Search API 返回的搜索结果（3 个类目）
题库/          ← 三个类目的提示词库（含品牌表/分层断言/竞品溯源）
分析存档/       ← analyze_final.py 的 stdout/json 输出（数字溯源用）
采集日志/       ← 采集脚本运行日志
算法脚本/       ← 全部分析/验证/采集脚本副本
```

## 数据文件说明

| 文件 | 类目 | 引擎 | 采集方式 | 有效样本 |
|---|---|---|---|---|
| 豆包/美容仪_samples.jsonl | 美容仪·斐驰 | 豆包网页端 | 浏览器自动化 | 226 |
| 豆包/按摩椅_samples.jsonl | 按摩椅·松胜 | 豆包网页端 | 浏览器自动化 | 260 |
| 豆包/水裹_samples.jsonl | 深圳汤泉·水裹+ | 豆包网页端 | 浏览器自动化 | 260 |
| DeepSeek/美容仪_search_results.jsonl | 美容仪 | DeepSeek Search API | API 调用 | 114 query |
| DeepSeek/按摩椅_search_results.jsonl | 按摩椅 | DeepSeek Search API | API 调用 | 104 query |
| DeepSeek/水裹_search_results.jsonl | 深圳汤泉 | DeepSeek Search API | API 调用 | 100 query |

## 数据字段说明（JSONL 每行一条记录）

### 豆包数据字段
| 字段 | 含义 |
|---|---|
| prompt_id / text / intent | 题目 ID / 原文 / 意图标签 |
| run_idx | 第几遍（两阶段设计：1-2 全员，3-5 摇摆加跑） |
| account | 采集账号（acc1/acc2/acc3） |
| answer | AI 回答全文 |
| brand_mentioned | 本品牌是否被提及（bool） |
| competitors | 答案中出现的竞品名列表 |
| search_triggered | 是否触发联网检索（bool） |
| citations | 引用列表（每条含 title/url/num） |
| citation_hosts | 引用域名去重列表 |
| own_brand_aliases | 本品牌别名表（采集口径落盘） |
| ok | 是否有效（answer 长度 >40） |

### DeepSeek Search API 数据字段
| 字段 | 含义 |
|---|---|
| query | 搜索词 |
| results[].title | 页面标题 |
| results[].url | 页面 URL |
| results[].snippet | 短摘要 |
| results[].summary | 长摘要 |
| results[].rerank_score | 排序分 0-3（≥1.5 优质） |
| results[].authority | 权威性 0-4（≥3 极权威） |
| results[].date | 发布日期 |
| results[].content | 网页正文（need_content=true 时） |


### 补充数据文件（六轮审核后补入）

| 文件 | 位置 | 说明 |
|---|---|---|
| 豆包/compare_accounts.jsonl | 账号对照实验数据 | 75 行（7 题 × 3 遍 × 3 账号 + 12 行零星） |
| 豆包/accounts.json | 三账号配置（profile 路径 + 端口） | 3 条 |
| 豆包/samples_anonymous.jsonl | 匿名账号测试数据 | 少量 |
| DeepSeek/ds_cross_analysis.json | 双引擎交叉分析结果 json | 松胜 + 水裹引用结构 |
| DeepSeek/美容仪_search_results.jsonl | 美容仪 114 题 DeepSeek 搜索结果 | 补入（此前缺失） |
| 分析存档/perm_v16_output.txt | 置换检验 stdout 存档 | 两档功效自检 + mix 扫描 |
| 分析存档/final_*_numbers.json | 各类目分析 json 落盘 | 含 brand_rank、hyper、r 等全部数字 |

## 复算命令

```bash
# 美容仪基线
python analyze_final.py > 美容仪_output.txt

# 按摩椅基线
python analyze_final.py --prompts 题库/按摩椅_104条.json --data 豆包/按摩椅_samples.jsonl --json-out 按摩椅.json

# 水裹基线
python analyze_final.py --prompts 题库/汤泉_100条.json --data 豆包/水裹_samples.jsonl --json-out 水裹.json

# DeepSeek Search API
python ds_geoscout.py --prompts 题库/按摩椅_104条.json
```
