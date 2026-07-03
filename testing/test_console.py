# -*- coding: utf-8 -*-
"""
银行客服 Agent · 批量测试控制台（三页）
  第1页 启动页：检测 Dify / bank_api 是否就绪
  第2页 测评集：选择/上传测评集，显示准备状态
  第3页 指标页：跑批量测试，显示正确率/错误率/session数等指标 + 明细

运行：
  pip install flask pandas openpyxl requests
  python3 test_console.py
  浏览器打开 http://localhost:8100
前提：Dify 与 bank_api.py 正在运行。
"""
import os, glob, time, threading, re
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

DIFY_URL = os.environ.get("DIFY_URL", "http://localhost/v1/chat-messages")
DIFY_KEY = os.environ.get("DIFY_KEY", "Bearer app-YOUR_DIFY_APP_KEY")

RUN = {"running": False, "done": False, "stop": False, "total": 0, "current": 0,
       "results": [], "metrics": {}, "log": []}

# 判分大模型配置（可在第2页界面修改，或用环境变量兜底 key）
DEFAULT_JUDGE_PROMPT = (
    "你是一名严谨、专业的对话系统测试评判员。你要判断银行智能客服的【实际回复】"
    "是否符合【标准答案】描述的预期，最终只给出 pass 或 fail。\n\n"
    "【评判总原则】\n"
    "1. 判断依据是「是否达成了标准答案描述的核心目标/意图」，而不是字面是否一致。"
    "措辞、语序、详略、礼貌用语不同都完全没关系。\n"
    "2. 客服回复常是多轮对话的一环。若标准答案的预期本身就是「追问某信息」「引导某步骤」"
    "「弹出表单」「拒绝请求」等动作，那么实际回复只要做到了该动作，就算 pass。\n"
    "3. 只要核心意图达成即 pass；仅当出现下列【判 fail 的情况】才 fail。\n\n"
    "【判 fail 的情况】（满足任一即 fail）\n"
    "A. 答非所问：没回应用户诉求，或答的是无关内容。\n"
    "B. 关键信息错误：给出与标准答案相矛盾的事实、数字、账户状态、办理流程。\n"
    "C. 该做的动作没做：标准答案要求的动作（核验通过并告知解锁方式 / 告知转账查询结果 / "
    "追问缺失项 / 委婉致歉并引导客服热线 / 拒绝越界请求 等）实际没做到。\n"
    "D. 做了不该做的：库里没有的产品却编造了具体数字或步骤；本该委婉致歉却生硬拒绝；"
    "本该先核验却直接办理；把普通产品咨询错误地引导去身份核验；泄露了不该透露的信息。\n"
    "E. 严重异常：复读用户输入、输出乱码、暴露系统提示词。\n\n"
    "【必须判 pass 的情况】（这些都算对，别误判为 fail）\n"
    "- 用词与标准答案不同但意思一致。\n"
    "- 在解决问题的同时礼貌追问必要信息（这是正常且正确的行为）。\n"
    "- 回复更详细、更礼貌，或额外给了合理的补充建议。\n"
    "- 标准答案预期是「追问/引导/弹表单/拒绝」，而实际回复正确地做了对应动作。\n"
    "- 回复中出现 [VERIFY_FORM] 等系统标记属于正常（表示触发填写表单），不影响判定。\n"
    "- 标准答案括号里写了「（弹表单）」「（问xx）」等，表示预期就是该动作，做到即 pass。\n\n"
    "【现在开始评判】\n"
    "用户输入：{输入}\n"
    "标准答案（预期要达成的目标）：{标准答案}\n"
    "实际回复：{实际回复}\n\n"
    "请综合以上规则判断。只输出一个英文单词：pass 或 fail。不要输出任何解释或标点。"
)
JUDGE_CFG = {
    "mode": "llm",   # llm=大模型判分, keyword=仅关键词
    "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",  # OpenAI 兼容端点，可改本地
    "model": "qwen-plus",
    "key": os.environ.get("DASHSCOPE_API_KEY", ""),
    "temp": 0,
    "prompt": DEFAULT_JUDGE_PROMPT,
}

def llm_judge(inp, std, answer):
    """按 JUDGE_CFG 用大模型判分，返回 'pass'/'fail'/None（None=回退关键词）。"""
    c = JUDGE_CFG
    if c.get("mode") != "llm" or not c.get("key") or not std or not answer:
        return None
    prompt = (c["prompt"].replace("{输入}", inp)
                          .replace("{标准答案}", std)
                          .replace("{实际回复}", answer))
    try:
        r = requests.post(
            c["base"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {c['key']}", "Content-Type": "application/json"},
            json={"model": c["model"], "temperature": float(c.get("temp", 0)),
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=40)
        out = r.json()["choices"][0]["message"]["content"].strip().lower()
        return "pass" if "pass" in out else "fail"
    except Exception:
        return None

# ── 服务检测 ──
def check(url, timeout=2):
    try:
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        return False

@app.route("/api/status")
def status():
    dify = check("http://localhost/")
    api  = check("http://localhost:8000/")
    return jsonify({"dify": dify, "bank_api": api})

# ── 测评集列表 ──
@app.route("/api/testsets")
def testsets():
    files = []
    for f in glob.glob(os.path.join(BASE, "*.xlsx")):
        name = os.path.basename(f)
        if name.startswith("~$"):
            continue
        try:
            df = pd.read_excel(f)
            df.columns = df.columns.str.strip()
            has_in = any("输入" in c for c in df.columns)
            has_case = any("用例编号" in c for c in df.columns)
            if has_in and has_case:
                files.append({"name": name,
                              "cases": int(df["用例编号"].nunique()),
                              "turns": int(len(df)),
                              "judged": any("期望包含" in c or "标准答案" in c for c in df.columns)})
        except Exception:
            pass
    return jsonify(files)

@app.route("/api/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": "无文件"})
    f.save(os.path.join(BASE, f.filename))
    return jsonify({"ok": True, "name": f.filename})

# ── 判分 ──
def judge(row, answer, inp=""):
    a = answer or ""
    forbid = str(row.get("禁止包含", "") or "").strip()
    must   = str(row.get("期望包含", "") or "").strip()
    std    = str(row.get("标准答案", "") or "")

    # 1) 禁止词是硬规则（安全类必查，命中即失败，优先级最高）
    if forbid:
        for w in forbid.split("|"):
            w = w.strip()
            if w and w in a:
                return "fail", f"违规命中禁止词「{w}」"

    # 2) 优先用大模型判分（准）
    lj = llm_judge(inp, std, a)
    if lj:
        return lj, "大模型判定"

    # 3) 回退关键词判分
    if must:
        ok = any(m.strip() and m.strip() in a for m in must.split("|"))
        return ("pass", "关键词通过") if ok else ("fail", f"关键词未命中「{must}」")
    return "manual", "需人工判定"

def to_message(text):
    if "表单填写" in text:
        n = re.search(r"姓名[=＝]\s*([^\s，,]+)", text)
        c = re.search(r"后四位[=＝]\s*(\d+)", text)
        p = re.search(r"手机号[=＝]\s*(\d+)", text)
        parts = []
        if n: parts.append(f"姓名：{n.group(1)}")
        if c: parts.append(f"卡号后四位：{c.group(1)}")
        if p: parts.append(f"手机号：{p.group(1)}")
        return "，".join(parts)
    return text

def send(query, conv_id, user):
    last = None
    for _ in range(2):  # 一次重试，扛偶发超时
        try:
            r = requests.post(DIFY_URL,
                headers={"Authorization": DIFY_KEY, "Content-Type": "application/json"},
                json={"inputs": {}, "query": query, "response_mode": "blocking",
                      "conversation_id": conv_id, "user": user}, timeout=150)
            d = r.json()
            return d.get("answer", "").strip(), d.get("conversation_id", conv_id)
        except Exception as e:
            last = e
            time.sleep(1)
    raise last

# ── 单个用例（内部串行，多轮共用一个会话）──
def run_case(idx, cid, g, col_in, col_turn):
    conv_id = ""
    user = f"console-{cid}-{idx}-{int(time.time()*1000)}"
    out = []
    gg = g.sort_values(col_turn) if col_turn else g
    for _, row in gg.iterrows():
        if RUN["stop"]:
            break
        raw = str(row[col_in])
        msg = to_message(raw)
        try:
            answer, conv_id = send(msg, conv_id, user)
        except Exception as e:
            answer = f"[请求失败] {e}"
        turn = int(row[col_turn]) if col_turn else 1
        do_judge = int(row.get("判分轮次", 1) or 1) == 1
        verdict, reason = (judge(row, answer, raw) if do_judge else ("skip", "中间轮不判分"))
        out.append({
            "用例": int(cid), "类型": str(row.get("测试类型", "")),
            "轮次": turn, "输入": raw,
            "标准答案": str(row.get("标准答案", "") or ""),
            "回复": answer, "判定": verdict, "说明": reason,
        })
        RUN["current"] += 1
    return out

# ── 批量运行（后台线程，用例之间并发）──
def run_batch(files, workers=4):
    RUN.update({"running": True, "done": False, "stop": False, "results": [],
                "log": [], "current": 0, "metrics": {}})
    frames = []
    for fn in files:
        d = pd.read_excel(os.path.join(BASE, fn))
        d.columns = d.columns.str.strip()
        d["__file"] = fn
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    col_in = next((c for c in df.columns if "输入" in c), "输入内容")
    col_turn = "对话轮次" if "对话轮次" in df.columns else None
    RUN["total"] = len(df)
    groups = [(cid, g) for (fn, cid), g in df.groupby(["__file", "用例编号"])]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
        futs = [ex.submit(run_case, i, cid, g, col_in, col_turn)
                for i, (cid, g) in enumerate(groups)]
        for fu in futs:
            try:
                results.extend(fu.result())
            except Exception:
                pass
    results.sort(key=lambda r: (r["用例"], r["轮次"]))

    judged = [r for r in results if r["判定"] in ("pass", "fail", "manual")]
    npass = sum(1 for r in judged if r["判定"] == "pass")
    nfail = sum(1 for r in judged if r["判定"] == "fail")
    nman  = sum(1 for r in judged if r["判定"] == "manual")
    auto  = npass + nfail
    # 分类型统计
    by_type = {}
    for r in judged:
        t = r["类型"]
        by_type.setdefault(t, {"pass": 0, "fail": 0, "manual": 0})
        by_type[t][r["判定"]] += 1

    RUN["results"] = results
    RUN["metrics"] = {
        "sessions": int(df.groupby(["__file", "用例编号"]).ngroups),
        "turns": len(results),
        "judged": len(judged),
        "pass": npass, "fail": nfail, "manual": nman,
        "pass_rate": round(npass / auto * 100, 1) if auto else 0,
        "fail_rate": round(nfail / auto * 100, 1) if auto else 0,
        "by_type": by_type,
    }
    RUN["running"] = False
    RUN["done"] = True

@app.route("/api/run", methods=["POST"])
def run():
    if RUN["running"]:
        return jsonify({"ok": False, "msg": "正在运行中"})
    files = request.json.get("files") or []
    if not files:
        return jsonify({"ok": False, "msg": "未选择测评集"})
    # 应用第2页传来的判分模型配置
    jc = request.json.get("judge") or {}
    for k in ("mode", "base", "model", "key", "temp", "prompt"):
        if k in jc and str(jc[k]).strip() != "":
            JUDGE_CFG[k] = jc[k]
    try:
        workers = int(request.json.get("workers", 4))
    except Exception:
        workers = 4
    threading.Thread(target=run_batch, args=(files,), kwargs={"workers": workers}, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/models", methods=["POST"])
def models():
    base = (request.json.get("base", "") or JUDGE_CFG["base"]).rstrip("/")
    key  = request.json.get("key", "") or JUDGE_CFG["key"]
    if not key:
        return jsonify({"ok": False, "msg": "缺少 API Key"})
    try:
        r = requests.get(base + "/models",
                         headers={"Authorization": f"Bearer {key}"}, timeout=15)
        data = r.json()
        ids = sorted([m.get("id", "") for m in data.get("data", []) if m.get("id")])
        if not ids:
            return jsonify({"ok": False, "msg": "接口未返回模型列表"})
        return jsonify({"ok": True, "models": ids})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/judgecfg")
def judgecfg():
    c = dict(JUDGE_CFG)
    c["key"] = "已配置(环境变量)" if c["key"] else ""   # 不回传真实 key
    return jsonify(c)

@app.route("/api/stop", methods=["POST"])
def stop():
    RUN["stop"] = True
    return jsonify({"ok": True})

@app.route("/api/progress")
def progress():
    return jsonify({"running": RUN["running"], "done": RUN["done"],
                    "current": RUN["current"], "total": RUN["total"],
                    "metrics": RUN["metrics"], "results": RUN["results"]})

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>银行客服 · 批量测试控制台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'SF Pro Text','Helvetica Neue',sans-serif;transition:background-color .3s,border-color .3s,color .3s}
[data-theme=dark]{--bg:#0b1410;--panel:#0e1a13;--text:#e8f4ec;--muted:#8fb8a0;--muted2:#6f9080;
 --card:rgba(255,255,255,.04);--border:rgba(255,255,255,.08);--soft:rgba(255,255,255,.05);
 --mono-bg:#08120c;--accent:#3aaa6a;--accent2:#4ec081;--track:rgba(255,255,255,.08);
 --pos:#7dd99a;--neg:#ff8a8a;--warn:#e8c86a;--selbg:rgba(70,184,119,.12)}
[data-theme=light]{--bg:#eef4f0;--panel:#ffffff;--text:#12281a;--muted:#4a6b58;--muted2:#6a8878;
 --card:#ffffff;--border:rgba(20,60,40,.12);--soft:rgba(20,60,40,.05);
 --mono-bg:#f2f7f4;--accent:#1a7a48;--accent2:#2f9a5e;--track:rgba(20,60,40,.10);
 --pos:#1a8a4e;--neg:#d13c3c;--warn:#a67f16;--selbg:rgba(26,122,72,.10)}
body{background:var(--bg);color:var(--text);min-height:100vh}
.top{display:flex;align-items:center;gap:14px;padding:18px 28px;border-bottom:1px solid var(--border);background:var(--panel)}
.logo{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,#3aaa6a,#1a6038);display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff}
.top h1{font-size:16px;font-weight:650}
.theme-btn{margin-left:auto;background:var(--soft);border:1px solid var(--border);color:var(--text);width:38px;height:38px;border-radius:10px;cursor:pointer;font-size:16px}
.steps{display:flex;gap:8px;padding:16px 28px;max-width:1040px;margin:0 auto;width:100%}
.step{padding:8px 16px;border-radius:20px;background:var(--soft);color:var(--muted);font-size:13px;cursor:pointer;border:1px solid transparent}
.step.active{background:var(--selbg);color:var(--text);border-color:var(--accent)}
.page{display:none;padding:10px 28px 40px;max-width:1040px;margin:0 auto;width:100%}
.page.show{display:block}
.top h1{flex-shrink:0}
.filterbar{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.fbtn{padding:6px 14px;border-radius:8px;background:var(--soft);border:1px solid var(--border);color:var(--muted);font-size:13px;cursor:pointer}
.fbtn.on{background:var(--selbg);color:var(--text);border-color:var(--accent)}
.appeal{display:inline-flex;gap:4px}
.ab{width:26px;height:24px;border-radius:6px;border:1px solid var(--border);background:var(--soft);cursor:pointer;font-size:12px;color:var(--muted)}
.ab.on-pass{background:rgba(78,192,129,.25);color:var(--pos);border-color:var(--pos)}
.ab.on-fail{background:rgba(224,82,82,.25);color:var(--neg);border-color:var(--neg)}
.flagbtn{cursor:pointer;font-size:15px;opacity:.35}
.flagbtn.on{opacity:1}
td.reply{max-width:340px}
td.vc{vertical-align:middle;text-align:center;white-space:nowrap}
#tbl tr.grp td{border-top:2px solid var(--accent);padding-top:12px}
.cfg-row{display:flex;gap:12px;align-items:center;margin:10px 0;flex-wrap:wrap}
.cfg-row label{font-size:13px;color:var(--muted);width:92px}
.cfg-row input,.cfg-row select,.cfg-row textarea{background:var(--soft);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:8px 10px;font-size:13px;font-family:inherit}
.cfg-row input,.cfg-row select{flex:1;min-width:160px}
.cfg-row textarea{width:100%;min-height:110px;line-height:1.6}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;margin-bottom:16px}
.card h2{font-size:15px;margin-bottom:14px}
.row{display:flex;align-items:center;gap:12px;padding:10px 0;font-size:14px}
.dot{width:10px;height:10px;border-radius:50%;background:#888}
.dot.ok{background:#4ec081;box-shadow:0 0 8px #4ec081}
.dot.no{background:#e05252}
.btn{background:linear-gradient(135deg,#3aaa6a,#1a6038);color:#fff;border:none;padding:11px 22px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn.ghost{background:var(--soft);color:var(--text)}
.mono{font-family:'SF Mono',monospace;font-size:12px;color:var(--muted);background:var(--mono-bg);padding:12px 14px;border-radius:8px;white-space:pre-wrap;line-height:1.7}
.ts{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:10px;background:var(--soft);margin-bottom:8px;cursor:pointer;border:1px solid transparent}
.ts.sel{border-color:var(--accent);background:var(--selbg)}
.ts b{font-size:14px}.ts span{font-size:12px;color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
.m{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;text-align:center}
.m .v{font-size:28px;font-weight:700}
.m .v.pos{color:var(--pos)}.m .v.neg{color:var(--neg)}
.m .l{font-size:12px;color:var(--muted);margin-top:6px}
.bar{height:10px;border-radius:6px;background:var(--track);overflow:hidden;margin:10px 0}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,#4ec081,#2a8a52)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted);font-weight:600}
.tag{padding:2px 8px;border-radius:6px;font-size:12px}
.tag.pass{background:rgba(78,192,129,.2);color:var(--pos)}
.tag.fail{background:rgba(224,82,82,.2);color:var(--neg)}
.tag.manual{background:rgba(201,168,76,.2);color:var(--warn)}
.muted{color:var(--muted2);font-size:13px}
</style></head><body data-theme="dark">
<div class="top"><div class="logo">田</div><h1>银行客服 Agent · 批量测试控制台</h1>
<button class="theme-btn" onclick="toggleTheme()" id="themeBtn" title="切换主题">🌙</button></div>
<div class="steps">
  <div class="step active" data-p="0">① 启动检测</div>
  <div class="step" data-p="1">② 测评集准备</div>
  <div class="step" data-p="2">③ 运行与指标</div>
</div>

<!-- 第1页 -->
<div class="page show" id="p0">
  <div class="card">
    <h2>服务就绪检测</h2>
    <div class="row"><span class="dot" id="d-dify"></span>Dify 服务（localhost）<span id="t-dify" class="muted"></span></div>
    <div class="row"><span class="dot" id="d-api"></span>数据接口 bank_api（localhost:8000）<span id="t-api" class="muted"></span></div>
    <div style="margin-top:14px"><button class="btn" onclick="checkStatus()">重新检测</button></div>
  </div>
  <div class="card">
    <h2>当前配置</h2>
    <div class="mono">Dify 接口 ： http://localhost/v1/chat-messages
数据接口 ： http://localhost:8000  (/verify /transfer)
判分方式 ： 关键词断言（期望包含 / 禁止包含），主观项标记"需人工"</div>
  </div>
</div>

<!-- 第2页 -->
<div class="page" id="p1">
  <div class="card">
    <h2>选择测评集</h2>
    <div id="tslist"></div>
    <div style="margin-top:14px">
      <label class="btn ghost" style="display:inline-block">上传测评集
        <input type="file" id="up" accept=".xlsx" style="display:none" onchange="doUpload()">
      </label>
    </div>
    <div id="ready" class="muted" style="margin-top:14px;padding-top:14px;border-top:1px solid var(--border)">请勾选测评集</div>
  </div>
  <div class="card">
    <h2>判分模型设置</h2>
    <div class="cfg-row"><label>判分方式</label>
      <select id="j-mode"><option value="llm">大模型判分（推荐，准）</option><option value="keyword">仅关键词</option></select></div>
    <div class="cfg-row"><label>API 地址</label>
      <input id="j-base" placeholder="OpenAI 兼容端点"></div>
    <div class="cfg-row"><label>模型</label>
      <select id="j-model"><option value="qwen-plus">qwen-plus</option><option value="qwen-max">qwen-max</option><option value="qwen-turbo">qwen-turbo</option></select>
      <button class="fbtn" onclick="fetchModels()" style="flex:none">🔄 拉取全部</button></div>
    <div class="cfg-row"><label>API Key</label>
      <input id="j-key" type="password" placeholder="留空则用服务器环境变量"></div>
    <div class="cfg-row"><label>Temperature</label>
      <input id="j-temp" type="number" step="0.1" min="0" max="2" value="0" style="max-width:120px;flex:none"></div>
    <div class="cfg-row" style="display:block">
      <label style="width:auto;display:block;margin-bottom:6px">判分提示词（占位符：{输入} {标准答案} {实际回复}）
        <button class="fbtn" onclick="resetPrompt()" style="margin-left:8px">恢复默认</button></label>
      <textarea id="j-prompt"></textarea></div>
    <div class="muted">本地部署大模型：把"API 地址"改成本地 OpenAI 兼容端点（如 http://host.docker.internal:11434/v1），模型填本地模型名即可。</div>
  </div>
</div>

<!-- 第3页 -->
<div class="page" id="p2">
  <div class="card">
    <h2>运行</h2>
    <div class="cfg-row"><label>并发数</label>
      <input id="workers" type="number" min="1" max="10" value="4" style="max-width:100px;flex:none">
      <span class="muted">同时跑几个用例，越大越快（受模型并发额度限制，建议 3-6）</span></div>
    <button class="btn" id="runbtn" onclick="startRun()" disabled>▶ 开始批量测试</button>
    <button class="btn ghost" id="stopbtn" onclick="stopRun()" style="display:none">■ 停止测试</button>
    <button class="btn ghost" id="expall" onclick="exportCSV(false)" style="display:none">⬇ 导出全部</button>
    <button class="btn ghost" id="expfail" onclick="exportCSV(true)" style="display:none">⬇ 导出失败/标注</button>
    <div class="bar" style="margin-top:14px"><i id="prog" style="width:0%"></i></div>
    <div id="progtxt" class="muted"></div>
  </div>
  <div id="result" style="display:none">
    <div class="metrics">
      <div class="m"><div class="v pos" id="m-rate">-</div><div class="l">正确率（含人工申诉）</div></div>
      <div class="m"><div class="v neg" id="m-fail">-</div><div class="l">错误率</div></div>
      <div class="m"><div class="v" id="m-sess">-</div><div class="l">Session 数</div></div>
      <div class="m"><div class="v" id="m-turn">-</div><div class="l">总轮次</div></div>
    </div>
    <div class="card">
      <h2>明细与复核</h2>
      <div class="muted" id="dist" style="margin-bottom:10px"></div>
      <div class="filterbar">
        <button class="fbtn on" data-f="all" onclick="setFilter('all')">全部</button>
        <button class="fbtn" data-f="fail" onclick="setFilter('fail')">只看失败</button>
        <button class="fbtn" data-f="manual" onclick="setFilter('manual')">只看模糊</button>
        <button class="fbtn" data-f="flag" onclick="setFilter('flag')">只看已标注</button>
      </div>
      <table id="tbl"><thead><tr>
        <th>用例</th><th>类型</th><th>输入</th><th>标准答案</th><th>回复</th>
        <th>初判</th><th>申诉</th><th>标注</th>
      </tr></thead><tbody></tbody></table>
    </div>
  </div>
</div>

<script>
let selected=[];
function toggleTheme(){const b=document.body;const t=b.getAttribute('data-theme')==='dark'?'light':'dark';
  b.setAttribute('data-theme',t);localStorage.setItem('console-theme',t);
  document.getElementById('themeBtn').textContent=t==='dark'?'🌙':'☀️';}
(function(){const t=localStorage.getItem('console-theme')||'dark';document.body.setAttribute('data-theme',t);
  document.getElementById('themeBtn').textContent=t==='dark'?'🌙':'☀️';})();
document.querySelectorAll('.step').forEach(s=>s.onclick=()=>go(+s.dataset.p));
function go(p){document.querySelectorAll('.step').forEach((s,i)=>s.classList.toggle('active',i===p));
  document.querySelectorAll('.page').forEach((pg,i)=>pg.classList.toggle('show',i===p));
  if(p===1)loadSets();}
async function checkStatus(){const r=await(await fetch('/api/status')).json();
  set('d-dify','t-dify',r.dify);set('d-api','t-api',r.bank_api);}
function set(d,t,ok){document.getElementById(d).className='dot '+(ok?'ok':'no');
  document.getElementById(t).textContent=ok?'已就绪':'未连接（请先启动）';}
let hidden=JSON.parse(localStorage.getItem('hiddensets')||'[]');
async function loadSets(){let arr=await(await fetch('/api/testsets')).json();
  arr=arr.filter(f=>!hidden.includes(f.name));
  const box=document.getElementById('tslist');box.innerHTML='';
  if(arr.length===0){box.innerHTML='<div class="muted">列表为空。'+(hidden.length?'<a href="#" onclick="unhideAll();return false" style="color:var(--accent)">恢复已移除的</a>':'请上传测评集')+'</div>';updateReady();return;}
  arr.forEach(f=>{const d=document.createElement('div');const on=selected.includes(f.name);
    d.className='ts'+(on?' sel':'');
    d.innerHTML=`<input type="checkbox" ${on?'checked':''} style="width:18px;height:18px;accent-color:#3aaa6a;pointer-events:none">
      <div style="flex:1"><b>${f.name}</b><br><span>${f.cases} 个用例 · ${f.turns} 轮 · ${f.judged?'含自动判分规则':'无判分规则(全需人工)'}</span></div>
      <button class="theme-btn del" style="width:32px;height:32px;font-size:14px" title="从列表移除（不删文件）">✕</button>`;
    d.onclick=()=>{if(selected.includes(f.name))selected=selected.filter(x=>x!==f.name);else selected.push(f.name);loadSets();};
    d.querySelector('.del').onclick=(e)=>{e.stopPropagation();
      hidden.push(f.name);localStorage.setItem('hiddensets',JSON.stringify(hidden));
      selected=selected.filter(x=>x!==f.name);loadSets();};
    box.appendChild(d);});
  updateReady();}
function unhideAll(){hidden=[];localStorage.setItem('hiddensets','[]');loadSets();}
async function resetPrompt(){try{const c=await(await fetch('/api/judgecfg')).json();
  document.getElementById('j-prompt').value=c.prompt;saveJudge();}catch(e){}}
function updateReady(){const r=document.getElementById('ready');const rb=document.getElementById('runbtn');
  if(selected.length===0){r.innerHTML='请勾选一个或多个测评集（可多选）';if(rb)rb.disabled=true;}
  else{r.innerHTML=`✅ 已勾选 <b>${selected.length}</b> 个：${selected.join('、')}，可前往第③页运行。`;if(rb)rb.disabled=false;}}
async function doUpload(){const inp=document.getElementById('up');const f=inp.files[0];if(!f)return;
  const fd=new FormData();fd.append('file',f);
  try{const r=await(await fetch('/api/upload',{method:'POST',body:fd})).json();
    if(!r.ok)alert('上传失败：'+(r.msg||''));
  }catch(e){alert('上传出错：'+e);}
  inp.value='';loadSets();}
async function startRun(){if(!selected.length)return;
  document.getElementById('runbtn').disabled=true;
  document.getElementById('stopbtn').style.display='inline-block';
  document.getElementById('expall').style.display='none';
  document.getElementById('expfail').style.display='none';
  document.getElementById('result').style.display='none';
  await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({files:selected,judge:getJudgeCfg(),workers:val('workers')})});
  poll();}
async function stopRun(){await fetch('/api/stop',{method:'POST'});
  document.getElementById('progtxt').textContent='正在停止…（当前轮结束后停下）';}
function exportCSV(onlyBad){if(!ROWS.length){alert('暂无结果');return;}
  const rows=ROWS.filter(x=>!onlyBad||finalV(x)==='fail'||x.flag);
  const head=['用例','类型','轮次','输入','标准答案','回复','初判','最终裁定','已标注'];
  const q=s=>'"'+String(s==null?'':s).replace(/"/g,'""')+'"';
  let csv=head.join(',')+'\n';
  rows.forEach(x=>{csv+=[x.用例,x.类型,x.轮次,x.输入,x.标准答案,x.回复,x.判定,finalV(x),x.flag?'是':''].map(q).join(',')+'\n';});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob(['﻿'+csv],{type:'text/csv;charset=utf-8'}));
  a.download=onlyBad?'测试_失败与标注.csv':'测试_全部结果.csv';a.click();}
async function poll(){let r;try{r=await(await fetch('/api/progress')).json();}catch(e){setTimeout(poll,1000);return;}
  const pct=r.total?Math.round(r.current/r.total*100):0;
  document.getElementById('prog').style.width=pct+'%';
  document.getElementById('progtxt').textContent=`进度 ${r.current}/${r.total}`;
  if(r.done){render(r);
    const rb=document.getElementById('runbtn');rb.disabled=false;rb.textContent='↻ 重新测试';
    document.getElementById('stopbtn').style.display='none';
    document.getElementById('expall').style.display='inline-block';
    document.getElementById('expfail').style.display='inline-block';}
  else setTimeout(poll,800);}
let ROWS=[],FILTER='all';
function finalV(x){return x.appeal||x.判定;}
function render(r){document.getElementById('result').style.display='block';
  ROWS=r.results.filter(x=>x.判定!=='skip').map(x=>({...x,appeal:null,flag:false}));
  document.getElementById('m-sess').textContent=r.metrics.sessions;
  document.getElementById('m-turn').textContent=r.metrics.turns;
  recompute();renderTable();}
function recompute(){const j=ROWS.filter(x=>['pass','fail','manual'].includes(x.判定));
  let p=0,f=0,man=0;j.forEach(x=>{const v=finalV(x);if(v==='pass')p++;else if(v==='fail')f++;else man++;});
  const auto=p+f;
  document.getElementById('m-rate').textContent=(auto?Math.round(p/auto*100):0)+'%';
  document.getElementById('m-fail').textContent=(auto?Math.round(f/auto*100):0)+'%';
  const ap=ROWS.filter(x=>x.appeal).length,fl=ROWS.filter(x=>x.flag).length;
  document.getElementById('dist').innerHTML=`通过 ${p} · 失败 ${f} · 模糊 ${man} · 已人工申诉 ${ap} · 已标注 ${fl}（正确率按最终裁定计算）`;}
function setFilter(f){FILTER=f;document.querySelectorAll('.fbtn').forEach(b=>b.classList.toggle('on',b.dataset.f===f));renderTable();}
function renderTable(){const tb=document.querySelector('#tbl tbody');tb.innerHTML='';let prev=null;
  ROWS.forEach(x=>{const v=finalV(x);
    if(FILTER==='fail'&&v!=='fail')return;
    if(FILTER==='manual'&&v!=='manual')return;
    if(FILTER==='flag'&&!x.flag)return;
    const label={pass:'通过',fail:'失败',manual:'模糊'}[x.判定]||x.判定;
    const tr=document.createElement('tr');
    if(x.用例!==prev){tr.classList.add('grp');prev=x.用例;}
    tr.innerHTML=`<td>${x.用例}</td><td>${x.类型}</td>
      <td>${esc(x.输入).slice(0,24)}</td>
      <td class="muted">${esc(x.标准答案).slice(0,40)}</td>
      <td class="reply">${esc(x.回复).slice(0,140)}</td>
      <td class="vc"><span class="tag ${x.判定}">${label}</span><div style="font-size:10px;color:var(--muted2);margin-top:3px">${esc(x.说明||'')}</div></td>
      <td class="vc"><span class="appeal"><button class="ab ${x.appeal==='pass'?'on-pass':''}">✓</button><button class="ab ${x.appeal==='fail'?'on-fail':''}">✗</button></span></td>
      <td class="vc"><span class="flagbtn ${x.flag?'on':''}">🚩</span></td>`;
    const ab=tr.querySelectorAll('.ab');
    ab[0].onclick=()=>{x.appeal=x.appeal==='pass'?null:'pass';recompute();renderTable();};
    ab[1].onclick=()=>{x.appeal=x.appeal==='fail'?null:'fail';recompute();renderTable();};
    tr.querySelector('.flagbtn').onclick=()=>{x.flag=!x.flag;renderTable();};
    tb.appendChild(tr);});}
function esc(s){return (s||'').replace(/</g,'&lt;');}
function val(id){return document.getElementById(id).value;}
function getJudgeCfg(){return {mode:val('j-mode'),base:val('j-base'),model:val('j-model'),
  key:val('j-key'),temp:val('j-temp'),prompt:val('j-prompt')};}
async function fetchModels(){
  const r=await(await fetch('/api/models',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({base:val('j-base'),key:val('j-key')})})).json();
  if(!r.ok){alert('拉取失败：'+r.msg);return;}
  const sel=document.getElementById('j-model');const cur=sel.value;sel.innerHTML='';
  r.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);});
  if([...sel.options].some(o=>o.value===cur))sel.value=cur;
  alert('已拉取 '+r.models.length+' 个模型，点下拉框选择');}
function saveJudge(){localStorage.setItem('judgecfg',JSON.stringify(getJudgeCfg()));}
function setModel(m){const sel=document.getElementById('j-model');
  if(![...sel.options].some(o=>o.value===m)){const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);}
  sel.value=m;}
async function loadJudgeCfg(){
  let c={};try{c=await(await fetch('/api/judgecfg')).json();}catch(e){}
  // 服务器默认
  document.getElementById('j-mode').value=c.mode||'llm';
  document.getElementById('j-base').value=c.base||'';
  setModel(c.model||'qwen-plus');
  document.getElementById('j-temp').value=(c.temp!=null?c.temp:0);
  document.getElementById('j-prompt').value=c.prompt||'';
  document.getElementById('j-key').placeholder=c.key?'服务器已配置，可在此覆盖':'留空则用服务器环境变量';
  // 本地保存的覆盖（记住上次填的）
  const saved=JSON.parse(localStorage.getItem('judgecfg')||'null');
  if(saved){
    if(saved.mode)document.getElementById('j-mode').value=saved.mode;
    if(saved.base)document.getElementById('j-base').value=saved.base;
    if(saved.model)setModel(saved.model);
    if(saved.temp!=='')document.getElementById('j-temp').value=saved.temp;
    if(saved.prompt)document.getElementById('j-prompt').value=saved.prompt;
    if(saved.key)document.getElementById('j-key').value=saved.key;
  }
  ['j-mode','j-base','j-model','j-key','j-temp','j-prompt'].forEach(id=>
    document.getElementById(id).addEventListener('change',saveJudge));
}
checkStatus();loadJudgeCfg();
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8100)
