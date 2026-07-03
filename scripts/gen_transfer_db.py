# -*- coding: utf-8 -*-
# 生成虚拟转账记录库。账号复用客户库卡号（方便交叉演示），金额随机。
# 不依赖真实语料。固定种子，与客户库、测评集同步。
import os, random
import pandas as pd

random.seed(20260703)

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CUST = os.path.join(_DATA, "customers.xlsx")
OUT = os.path.join(_DATA, "transfers.xlsx")

STATUS = [
    ("已原路退回", "款项已退回原账户，预计24小时内到账"),
    ("退汇处理中", "正在为您发起退汇，预计1个工作日内处理完成"),
    ("对方已入账", "对方账户已成功入账，请与收款方核实"),
    ("异常退回", "因对方账户状态异常，款项已退回您的原账户"),
    ("未核实到", "未查询到该笔转账记录，建议核实信息或前往网点"),
]

accounts = pd.read_excel(CUST, dtype=str)["卡号后4位"].tolist()

records, seen = [], set()
for acc in accounts:
    for _ in range(random.randint(1, 2)):
        amt = str(random.choice([random.randint(1, 999),
                                 random.randint(1000, 9999),
                                 random.randint(10000, 99999)]))
        if (acc, amt) in seen:
            continue
        seen.add((acc, amt))
        st, detail = random.choice(STATUS)
        records.append((acc, amt, st, detail))

df = pd.DataFrame(records, columns=["账号后4位", "转账金额", "转账状态", "说明"])
df.to_excel(OUT, index=False)

print(f"生成 {len(df)} 条转账记录 → {OUT}")
print(df.to_string(index=False))
