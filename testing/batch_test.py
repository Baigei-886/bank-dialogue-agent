# -*- coding: utf-8 -*-
"""
银行客服 Agent · 批量测试脚本
读取测评表 Excel，逐条调用 Dify API（多轮用例自动保持同一 conversation_id），
把实际回复写回一个结果 Excel，方便对照人工判分。

用法：
  pip install pandas openpyxl requests
  python3 batch_test.py
前提：Dify 正在运行、bank_api.py 正在运行。
"""
import os
import pandas as pd
import requests, time, re

# ── 配置（与前端 app.js 保持一致）──
DIFY_URL = os.environ.get("DIFY_URL", "http://localhost/v1/chat-messages")
DIFY_KEY = os.environ.get("DIFY_KEY", "Bearer app-YOUR_DIFY_APP_KEY")
_DATA    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
IN_FILE  = os.path.join(_DATA, "testset.xlsx")
OUT_FILE = os.path.join(_DATA, "批量测试结果.xlsx")
# ──────────────────────────────────

def to_message(text: str) -> str:
    """把"表单填写：姓名=X 卡号后四位=Y 手机号=Z"转成前端实际发送的消息格式。"""
    if "表单填写" in text:
        name  = re.search(r"姓名[=＝]\s*([^\s，,]+)", text)
        card  = re.search(r"后四位[=＝]\s*(\d+)", text)
        phone = re.search(r"手机号[=＝]\s*(\d+)", text)
        parts = []
        if name:  parts.append(f"姓名：{name.group(1)}")
        if card:  parts.append(f"卡号后四位：{card.group(1)}")
        if phone: parts.append(f"手机号：{phone.group(1)}")
        return "，".join(parts)
    return text

def send(query: str, conv_id: str, user: str):
    resp = requests.post(
        DIFY_URL,
        headers={"Authorization": DIFY_KEY, "Content-Type": "application/json"},
        json={
            "inputs": {}, "query": query, "response_mode": "blocking",
            "conversation_id": conv_id, "user": user,
        },
        timeout=90,
    )
    data = resp.json()
    return data.get("answer", "").strip(), data.get("conversation_id", conv_id)

def main():
    df = pd.read_excel(IN_FILE)
    df.columns = df.columns.str.strip()
    col_in = [c for c in df.columns if "输入内容" in c][0]
    col_turn = [c for c in df.columns if "轮次" in c][0]

    results = []
    for cid, g in df.groupby("用例编号"):
        conv_id = ""                       # 每个用例新开对话（多用户隔离 + 记忆干净）
        user = f"batchtest-{cid}-{int(time.time())}"
        print(f"\n===== 用例 {cid} =====")
        for _, row in g.sort_values(col_turn).iterrows():
            raw = str(row[col_in])
            # 纯观察项（如"针对以上任意回复观察"）跳过
            if "观察" in raw:
                answer = "(全局观察项，需人工看)"
            else:
                msg = to_message(raw)
                try:
                    answer, conv_id = send(msg, conv_id, user)
                except Exception as e:
                    answer = f"[请求失败] {e}"
            rec = row.to_dict()
            rec["实际结果"] = answer
            results.append(rec)
            print(f"  轮{row[col_turn]} | {raw[:24]}\n        → {answer[:60]}")
            time.sleep(0.4)

    out = pd.DataFrame(results)
    out.to_excel(OUT_FILE, index=False)
    print(f"\n全部完成，结果已写入：{OUT_FILE}")
    print(f"共 {out['用例编号'].nunique()} 个用例 / {len(out)} 轮")

if __name__ == "__main__":
    main()
