# -*- coding: utf-8 -*-
"""
GEO 首轮基线采样器 — 豆包网页端（生产版）
设计：50 提示词 × N 遍；每次开新对话（避免上下文污染）；全量留档 + 断点续跑。

用法：
  venv_python run_samples.py --runs 5 --limit 10        # 小试
  venv_python run_samples.py --runs 5                    # 全量 250 次
  断点续跑：samples.jsonl 里已有的 (prompt_id, run_idx) 自动跳过
"""
import argparse, asyncio, json, random, re, subprocess, socket, sys, time
from pathlib import Path
from datetime import datetime

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from geolib import read_jsonl, jdumps
except Exception:  # 采样器在 sampler/ 子目录下运行
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    from geolib import read_jsonl, jdumps

ROOT = Path(r"C:\Users\29496\geo-lab")
PROFILE = ROOT / "chrome-profile"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "samples.jsonl"
LOGS = ROOT / "logs"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9222
DOUBAO = "https://www.doubao.com/chat/"
ENGINE, ENDPOINT = "doubao", "web"

BRAND_ALIASES = ["斐驰", "fetrex"]
COMPETITORS = ["雅萌", "初普", "Tripollar", "宙斯", "极萌", "觅光", "Ulike", "大排灯",
               "ZIIP", "JOVS", "Nodoor", "慕苏", "纽立", "索朗特", "medicube", "theBeam"]

for d in (PROFILE, RAW, LOGS):
    d.mkdir(parents=True, exist_ok=True)


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOGS / "sampler.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def launch_chrome():
    args = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
            "--no-first-run", "--no-default-browser-check",
            # 并行必需：禁用后台标签页节流，否则非激活标签的答案渲染会被降频/暂停
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling",
            DOUBAO]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        s = socket.socket()
        try:
            s.connect(("127.0.0.1", PORT)); s.close()
            log(f"CDP {PORT} 就绪"); return True
        except Exception:
            pass
    return False


def done_keys(expect_nonzero=True):
    """已完成键集合。

    ⚠️ 断言兜底（第三方复核指出本规则此前只写在文档、未落地）：
    「吞异常 + 返回空集合」是数据管线最危险的失败模式——返回 0 与返回正常值
    在日志里长得一样，唯一后果是下次把全部样本重跑并静默覆盖旧记录。
    因此这里做两层断言：文件存在却读出 0 条、或读数明显偏小，都直接报错。
    """
    keys = set()
    n_lines = 0
    if OUT.exists():
        rows = read_jsonl(OUT)
        n_lines = len(rows)
        for r in rows:
            if r.get("ok"):
                keys.add((r["prompt_id"], r["run_idx"]))
        if expect_nonzero and n_lines > 0 and not keys:
            raise RuntimeError(
                f"{OUT} 有 {n_lines} 条记录但 ok 数为 0 —— 极可能是读取路径出了问题"
                f"（字段名变更/解析静默失败），拒绝以空集合继续，否则会全量重跑覆盖旧数据。")
        if expect_nonzero and n_lines > 0 and len(keys) < n_lines * 0.5:
            raise RuntimeError(
                f"{OUT} 有 {n_lines} 条记录但只有 {len(keys)} 条 ok —— 比例低于 50%，"
                f"疑似解析丢失，拒绝继续。确认无误请显式传 expect_nonzero=False。")
    return keys


def host_of(u):
    try:
        return re.sub(r"^www\.", "", u.split("//", 1)[1].split("/", 1)[0].lower())
    except Exception:
        return ""


def jdumps(obj):
    """写 JSONL 专用。
    必须转义 U+2028/U+2029 —— 它们是合法 JSON 字符，但 Python 的 str.splitlines()
    会把它们当换行，导致下游按行读取时把一条记录切成多条、解析失败、**静默丢样本**。
    （实测：抖音视频标题里就带 U+2028，240 行文件被 splitlines() 切成 256 行。）"""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


ANS_SEL = '[data-testid="message_text_content"]'
INPUT_SEL = 'div.tiptap.ProseMirror'
ACCOUNT = "phone_login_2026-10-08"          # 口径留痕：账号状态
SLEEP_MIN, SLEEP_MAX = 1.0, 3.0             # 采样间隔（实测验证码按次数触发，拉长间隔无效）
POLL_S = 1.5                                # 答案轮询间隔
ANSWER_TIMEOUT_S = 120                      # 单条答案等待上限
PARALLEL = 1                                # 并行标签页数
LOGIN_WALL_SIGNS = ["登录以解锁更多功能", "扫码登录", "手机号登录", "抖音一键登录"]


class LoginRequired(Exception):
    """未登录/额度用完，必须人工登录"""


class CaptchaRequired(Exception):
    """触发人机验证，必须人工过验证码"""


CAPTCHA_SIGNS = ["请选择所有符合", "拖拽到这里", "拖动到下方", "拖动滑块"]
# 注意：不要拿「安全验证」「请完成验证」这类词做判据 —— 答案正文里会出现
# （实测 D01「美容仪是智商税吗」的答案里就有「没有安全验证」，导致误报停轮）


async def check_captcha(page):
    """检测人机验证弹窗。三重判据（缺一就会漏）：
    ① 主文档专有文案 ② 子 frame 内文案（豆包验证码在跨域 iframe 里，主文档读不到）
    ③ 结构：全屏固定遮罩 + 超高 z-index（验证码壳，实测 z≈111111）
    不要用「安全验证」「请完成验证」这类词——答案正文里会出现（实测误报过）。"""
    try:
        body = await page.evaluate("document.body.innerText") or ""
    except Exception:
        body = ""
    if any(s in body for s in CAPTCHA_SIGNS):
        return True

    # ② 子 frame（跨域 iframe 的文本主文档拿不到）
    try:
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            try:
                t = await fr.evaluate("document.body ? document.body.innerText : ''")
            except Exception:
                continue
            if not t:
                continue
            if any(s in t for s in CAPTCHA_SIGNS):
                return True
            if "提交" in t and ("刷新" in t or "反馈" in t):
                return True
    except Exception:
        pass

    # ③ 结构兜底：全屏固定超高 z-index 遮罩
    try:
        return await page.evaluate("""(() => {
          const els = Array.from(document.querySelectorAll('div,iframe'));
          return els.some(e => {
            const cs = getComputedStyle(e);
            if (cs.position !== 'fixed' || cs.display === 'none' || cs.visibility === 'hidden') return false;
            const z = parseInt(cs.zIndex || '0', 10);
            const r = e.getBoundingClientRect();
            return z >= 10000 && r.width > 400 && r.height > 400;
          });
        })()""")
    except Exception:
        return False


async def ensure_ready(page, rec):
    """确保页面就绪：输入框可见 + 对话模式 + 无登录墙（必须显式等输入框，domcontentloaded 不够）"""
    for attempt in range(3):
        try:
            await page.wait_for_selector(INPUT_SEL, timeout=20000, state="visible")
            ready = True
        except Exception:
            ready = False
        if ready:
            body = await page.evaluate("document.body.innerText") or ""
            if "登录以解锁" in body:
                raise LoginRequired("检测到登录墙")
            if await check_captcha(page):
                raise CaptchaRequired("检测到人机验证弹窗")
            if "有什么我能帮你的吗" not in body:
                m = await page.evaluate("""(() => {
                  const els = Array.from(document.querySelectorAll('div,span,button,a'));
                  const t = els.find(e => (e.innerText||'').trim()==='对话'
                            && e.getBoundingClientRect().y < 240);
                  if(!t) return 'NOT_FOUND';
                  t.click(); return 'clicked';
                })()""")
                await asyncio.sleep(2.5)
                body2 = await page.evaluate("document.body.innerText") or ""
                rec["mode_guard"] = m if "有什么我能帮你的吗" in body2 else f"FAILED({m})"
            return True
        rec["renav"] = rec.get("renav", 0) + 1
        await page.goto(DOUBAO, wait_until="domcontentloaded")
        await asyncio.sleep(3)
    return False


async def new_conversation(page):
    """开新对话：优先 Ctrl+Shift+K（实测按后回答容器归零），失败回退重新导航"""
    try:
        await page.keyboard.press("Control+Shift+KeyK")
        await asyncio.sleep(2.0)
        n = await page.evaluate(
            "document.querySelectorAll('[data-testid=\"message_text_content\"]').length")
        if n == 0:
            return "shortcut"
    except Exception:
        pass
    await page.goto(DOUBAO, wait_until="domcontentloaded")
    await asyncio.sleep(2.5)
    return "goto"


async def type_and_send(page, text, rec):
    """真实键盘输入 + 校验 + Enter（execCommand 会写进 DOM 但不进 SPA 状态，禁用）"""
    try:
        await page.locator(INPUT_SEL).first.click(timeout=10000)
    except Exception as e:
        rec["type_err"] = f"click:{str(e)[:80]}"
        return False
    await asyncio.sleep(0.4)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await asyncio.sleep(0.3)
    await page.keyboard.type(text, delay=25)
    await asyncio.sleep(0.6)
    got = await page.evaluate(
        "document.querySelector('div.tiptap.ProseMirror')?.innerText || ''")
    if text[:4] not in got:
        rec["type_err"] = f"verify_failed:{got[:40]!r}"
        return False
    await page.keyboard.press("Enter")
    return True


async def sample_once(page, prompt, run_idx, account=None):
    rec = {"prompt_id": prompt["id"], "intent": prompt["intent"],
           "brand_query": prompt.get("brand_query", False), "text": prompt["text"],
           "run_idx": run_idx, "engine": ENGINE, "endpoint": ENDPOINT,
           "account": account or ACCOUNT,
           "ts": datetime.now().isoformat(timespec="seconds"),
           "ok": False}

    rec["new_conv"] = await new_conversation(page)
    if not await ensure_ready(page, rec):
        rec["error"] = "page_not_ready"
        return rec
    if not await type_and_send(page, prompt["text"], rec):
        rec["error"] = rec.get("type_err", "send_failed")
        return rec

    answer, waited = "", 0
    for _ in range(int(ANSWER_TIMEOUT_S // POLL_S)):   # 超时上限（实测正常答案 ≤57s，120s 足够）
        await asyncio.sleep(POLL_S); waited += POLL_S
        if await check_captcha(page):
            raise CaptchaRequired("答题过程中弹出人机验证")
        try:
            st = await page.evaluate("""(s) => {
              // 关键：该 testid 同时匹配「用户提问」和「AI 回答」，
              // 用户气泡内含 datatype="query-source-paragraph-start"，必须排除
              const els = Array.from(document.querySelectorAll(s))
                .filter(e => !e.querySelector('[datatype="query-source-paragraph-start"]'));
              const last = els[els.length-1];
              return last ? {txt:last.innerText||'', streaming:last.getAttribute('data-streaming')} : null;
            }""", ANS_SEL)
        except Exception:
            st = None
        if st and st["txt"] and st["streaming"] == "false" and len(st["txt"]) > 40:
            await asyncio.sleep(2)
            st2 = await page.evaluate("""(s) => {
              const els = Array.from(document.querySelectorAll(s))
                .filter(e => !e.querySelector('[datatype="query-source-paragraph-start"]'));
              const last = els[els.length-1];
              return last ? (last.innerText||'') : '';
            }""", ANS_SEL)
            if st2 == st["txt"]:
                answer = st["txt"]; break
    rec["wait_s"] = waited
    rec["answer"] = answer
    rec["answer_len"] = len(answer)
    if not answer:
        rec["error"] = f"answer_timeout_after_{waited:.0f}s"   # v5：失败原因必须落字段（终审 N9）

    # 展开引用面板 + 抓检索词（查询扇出）
    claimed = None
    page_text = await page.evaluate("document.body.innerText")
    m = re.search(r"参考\s*(\d+)\s*篇资料", page_text)
    search_hit = re.search(r"搜索\s*(\d+)\s*个关键词", page_text)
    rec["search_triggered"] = bool(m or search_hit)   # 是否触发联网检索
    rec["search_keyword_count"] = int(search_hit.group(1)) if search_hit else None
    rec["search_keywords"] = []
    if m:
        claimed = int(m.group(1))
        try:
            await page.evaluate("""(() => {
              const els = Array.from(document.querySelectorAll('div,span,button'));
              const t = els.find(e => /参考\\s*\\d+\\s*篇资料/.test(e.innerText||'')
                                      && (e.className||'').toString().includes('cursor-pointer'));
              if(t){ t.scrollIntoView({block:'center'}); t.click(); return true; }
              return false;
            })()""")
            await asyncio.sleep(2.0)
            # 实测：面板无独立滚动容器（逐层查过 overflow:visible / scrollHeight==clientHeight），
            # 列表一次性全渲染 —— 无需滚动，之前那 3 次 scrollBy 是无效开销，已删
            # 检索词（查询扇出）要点开面板后才出现 —— 必须用展开后的文本重取
            after_text = await page.evaluate("document.body.innerText") or ""
            sh2 = re.search(r"搜索\s*(\d+)\s*个关键词", after_text)
            if sh2:
                tail = after_text[sh2.end():sh2.end() + 1200]
                seen, dedup = set(), []
                for k in re.findall(r"[“\"「『]([^”\"」』\n]{2,80})[”\"」』]", tail):
                    if k not in seen:
                        seen.add(k); dedup.append(k)
                rec["search_keywords"] = dedup[:12]
        except Exception as e:
            rec["cite_click_err"] = str(e)[:150]

    cites = await page.evaluate("""(() => {
      const seen=new Set(), out=[];
      document.querySelectorAll('a[href]').forEach(a => {
        const h=a.href;
        if(!/^https?:/.test(h) || h.includes('doubao.com')) return;
        if(seen.has(h)) return; seen.add(h);
        const t = (a.innerText||'').trim();
        const m = t.match(/^(\\d+)[.、]/);
        out.push({url:h, title:t.slice(0,200), num: m ? parseInt(m[1]) : null});
      });
      return out;
    })()""")
    rec["citations"] = cites
    rec["citation_count_claimed"] = claimed          # 引擎自述「参考 N 篇资料」
    rec["citation_count_listed"] = len(cites)        # 实际列出的引用清单条数（引用域统计的正确基数）

    # 完整性校验：编号是否从 1 连续排到 N（连续=列表完整，无懒加载/无隐藏条目）
    nums = sorted(c["num"] for c in cites if c.get("num"))
    rec["citation_list_complete"] = bool(nums) and nums == list(range(1, len(nums) + 1))
    rec["citation_nums"] = nums
    # 兼容旧字段
    rec["citation_count_captured"] = len(cites)
    rec["citation_hosts"] = sorted({host_of(c["url"]) for c in cites})

    low = (answer or "").lower()
    rec["brand_mentioned"] = any(a.lower() in low for a in BRAND_ALIASES)
    rec["competitors"] = [c for c in COMPETITORS if c.lower() in low]
    rec["own_brand_aliases"] = list(BRAND_ALIASES)   # v1.6：采集口径随记录落盘（可溯源）
    rec["ok"] = len(answer) > 40
    return rec


async def run(prompts, runs, limit, ids="", parallel=1):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        ctx = browser.contexts[0]
        # 关掉无关/重复标签页，只留一个豆包页（避免往错页面打字）
        keep = None
        for pg in list(ctx.pages):
            try:
                u = pg.url
            except Exception:
                continue
            if "doubao.com/chat" in u and keep is None:
                keep = pg
            elif "doubao.com" in u:
                try:
                    await pg.close()
                    log(f"关闭多余标签页：{u[:60]}")
                except Exception:
                    pass
        page = keep or (ctx.pages[0] if ctx.pages else await ctx.new_page())
        # 建立页面池：并行 = 每个 worker 独占一个标签页（互不干扰）
        pages = [page]
        for _ in range(max(0, parallel - 1)):
            pages.append(await ctx.new_page())
        for i, pg in enumerate(pages):
            # 关键：让每个标签页都"以为自己在前台"，避免后台节流导致答案不渲染
            try:
                cdp_s = await ctx.new_cdp_session(pg)
                await cdp_s.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            except Exception as e:
                log(f"页面{i} 焦点模拟失败：{str(e)[:60]}")
            for attempt in range(3):
                try:
                    await pg.goto(DOUBAO, wait_until="domcontentloaded", timeout=60000)
                    break
                except Exception as e:
                    log(f"页面{i} 导航第 {attempt+1} 次失败：{str(e)[:60]}")
                    await asyncio.sleep(5)
        log(f"页面池就绪：{len(pages)} 个标签页（并行度 {parallel}，已开焦点模拟+禁用后台节流）")
        await asyncio.sleep(3)

        done = done_keys()
        todo = [(pr, k) for pr in prompts for k in range(1, runs + 1)
                if (pr["id"], k) not in done]
        if ids:
            want = {s.strip() for s in ids.split(",") if s.strip()}
            todo = [(pr, k) for (pr, k) in todo if pr["id"] in want]
        if limit:
            todo = todo[:limit]
        log(f"待跑 {len(todo)} 条（已跳过 {len(done)} 条）；估算 "
            f"{len(todo)*20/60:.0f}–{len(todo)*35/60:.0f} 分钟")

        q = asyncio.Queue()
        for t in todo:
            q.put_nowait(t)
        t0 = time.time()
        state = {"ok": 0, "i": 0, "stop": False, "reason": None}
        lock = asyncio.Lock()

        def save(rec):
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(jdumps(rec) + "\n")

        async def worker(pg, wid):
            while not state["stop"]:
                try:
                    pr, k = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    rec = await sample_once(pg, pr, k)
                except (LoginRequired, CaptchaRequired) as e:
                    kind = "captcha_required" if isinstance(e, CaptchaRequired) else "login_required"
                    async with lock:
                        log(f"!! [w{wid}] 需要人工处理（{kind}：{e}）—— 全局停下，剩余任务保留")
                        log(f"   ⚠️ 请在那个 Chrome 窗口里人工完成验证/登录，然后重新运行本脚本")
                        state["stop"] = True
                        state["reason"] = kind
                        save({"prompt_id": pr["id"], "run_idx": k, "ok": False, "error": kind,
                              "text": pr["text"], "account": ACCOUNT,
                              "ts": datetime.now().isoformat(timespec="seconds"), "engine": ENGINE})
                    return
                except Exception as e:
                    rec = {"prompt_id": pr["id"], "run_idx": k, "ok": False,
                           "error": f"{type(e).__name__}:{str(e)[:180]}", "text": pr["text"],
                           "account": ACCOUNT,
                           "ts": datetime.now().isoformat(timespec="seconds"), "engine": ENGINE}
                async with lock:
                    save(rec)
                    state["ok"] += 1 if rec.get("ok") else 0
                    state["i"] += 1
                    i = state["i"]
                    el = time.time() - t0
                    log(f"[{i}/{len(todo)}]w{wid} {pr['id']}#{k} ok={rec.get('ok')} "
                        f"ans={rec.get('answer_len',0)} "
                        f"cites={rec.get('citation_count_captured',0)}/{rec.get('citation_count_claimed')} "
                        f"search={rec.get('search_triggered')} brand={rec.get('brand_mentioned')} "
                        f"{rec.get('wait_s','?')}s err={rec.get('error') or '-'} "
                        f"ETA{(el/i)*(len(todo)-i)/60:.0f}min")
                await asyncio.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

        await asyncio.gather(*[worker(pg, i) for i, pg in enumerate(pages)])
        log(f"完成：{state['ok']}/{len(todo)} 成功"
            + (f"（因 {state['reason']} 提前停止）" if state["stop"] else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", default=str(ROOT / "prompts" / "meirongyi_final_v2.json"),
                    help="提示词库；默认=当前 114 条版（旧 50 条版 meirongyi_baseline_v1.json 已弃用）")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="", help="逗号分隔的 prompt id 白名单，如 I01,C01,B01")
    ap.add_argument("--parallel", type=int, default=1, help="并行标签页数（>1 提速，但可能更早触发验证码）")
    ap.add_argument("--poll", type=float, default=1.5, help="答案轮询间隔秒")
    ap.add_argument("--sleep-min", type=float, default=1.0)
    ap.add_argument("--sleep-max", type=float, default=3.0)
    ap.add_argument("--out", default="", help="输出文件（默认 data/samples.jsonl；测试时可指向别处避免污染）")
    ap.add_argument("--brand", default="", help="本品牌别名（逗号分隔）；缺省读提示词 meta.own_brand，再缺省用模块默认")
    ap.add_argument("--competitors", default="", help="竞品表（逗号分隔）；缺省读提示词 meta.competitors，再缺省用模块默认")
    a = ap.parse_args()
    # 模块级直接赋值即可，run()/sample_once() 读的就是这些名字
    POLL_S, SLEEP_MIN, SLEEP_MAX = a.poll, a.sleep_min, a.sleep_max
    if a.out:
        OUT = Path(a.out)
    data = json.loads(Path(a.prompts).read_text(encoding="utf-8"))
    # 品牌表解析优先级（v1.6 规则：品牌清单显式声明）：
    #   ① --brand/--competitors 命令行（显式强制，最高）
    #   ② 提示词 meta.own_brand / meta.competitors（推荐：口径随题库单一来源）
    #   ③ 模块默认常量（美容仪/斐驰，向后兼容）
    meta = data.get("meta") or {}
    if a.brand:
        BRAND_ALIASES = [s.strip() for s in a.brand.split(",") if s.strip()]
    elif isinstance(meta.get("own_brand"), list) and meta["own_brand"]:
        BRAND_ALIASES = [str(s) for s in meta["own_brand"]]
    if a.competitors:
        COMPETITORS = [s.strip() for s in a.competitors.split(",") if s.strip()]
    elif isinstance(meta.get("competitors"), list) and meta["competitors"]:
        COMPETITORS = [str(s) for s in meta["competitors"]]
    log(f"品牌表：own={BRAND_ALIASES}｜竞品 {len(COMPETITORS)} 项：{COMPETITORS[:8]}...")
    if not launch_chrome():
        sys.exit(1)
    time.sleep(2)
    asyncio.run(run(data["prompts"], a.runs, a.limit, a.ids, a.parallel))
