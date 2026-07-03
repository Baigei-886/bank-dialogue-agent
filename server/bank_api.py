# -*- coding: utf-8 -*-
"""
银行客服 · 本地数据接口
- 实时读取 Excel，改 Excel 即更新数据，无需重启
- /verify   身份核验（姓名+卡号后4位+手机号）
- /transfer 转账查询（账号后4位+金额）
运行： python3 bank_api.py   （监听 8000 端口）
"""
from flask import Flask, request, jsonify
import pandas as pd
import re, os

app = Flask(__name__)
BASE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CUST  = os.path.join(BASE, "customers.xlsx")
TRANS = os.path.join(BASE, "transfers.xlsx")

def norm(s):
    """统一成纯净字符串，去掉 8834.0 这种小数尾巴"""
    s = str(s).strip()
    return re.sub(r"\.0$", "", s)

@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json(force=True, silent=True) or {}
    # 方式1：直接给 name/card/phone 字段（参数提取器）
    name  = norm(data.get("name", ""))
    card  = norm(data.get("card", ""))
    phone = norm(data.get("phone", ""))
    # 方式2：给整句 query（兼容表单提交），用正则解析
    if not (name and card and phone):
        query = str(data.get("query", ""))
        mn = re.search(r"姓名[：:]\s*([^\s，,]+)", query)
        mc = re.search(r"后四位[：:]\s*(\d{4})", query)
        mp = re.search(r"手机号[：:]\s*(\d{11})", query)
        name  = name  or (mn.group(1) if mn else "")
        card  = card  or (mc.group(1) if mc else "")
        phone = phone or (mp.group(1) if mp else "")

    if not (name and card and phone):
        return jsonify({"verified": "incomplete", "status": "", "name": ""})

    df = pd.read_excel(CUST, dtype=str)
    df.columns = df.columns.str.strip()
    for c in ["姓名", "卡号后4位", "注册手机号", "账户状态"]:
        df[c] = df[c].map(norm)

    row = df[(df["姓名"] == name) &
             (df["卡号后4位"] == card) &
             (df["注册手机号"] == phone)]
    if len(row):
        return jsonify({"verified": "true",
                        "status": row.iloc[0]["账户状态"],
                        "name": name})
    return jsonify({"verified": "false", "status": "", "name": ""})

@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.get_json(force=True, silent=True) or {}
    card   = norm(data.get("card", ""))
    amount = norm(data.get("amount", ""))
    if not (card and amount):
        return jsonify({"found": "incomplete", "status": "", "detail": ""})

    df = pd.read_excel(TRANS, dtype=str)
    df.columns = df.columns.str.strip()
    for c in ["账号后4位", "转账金额", "转账状态", "说明"]:
        df[c] = df[c].map(norm)

    row = df[(df["账号后4位"] == card) & (df["转账金额"] == amount)]
    if len(row):
        return jsonify({"found": "true",
                        "status": row.iloc[0]["转账状态"],
                        "detail": row.iloc[0]["说明"]})
    return jsonify({"found": "false", "status": "未核实到",
                    "detail": "未查询到该笔转账记录，建议核实信息或前往网点"})

@app.route("/", methods=["GET"])
def health():
    return "bank_api 运行中"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
