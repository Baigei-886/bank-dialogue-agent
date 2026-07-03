# -*- coding: utf-8 -*-
# 生成虚拟客户核验库。卡号后四位、手机号全随机，不依赖任何真实数据。
# 固定随机种子，重复运行结果一致，与 bank_api 读取的数据保持同步。
import os, random
import pandas as pd

random.seed(20260703)

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUT = os.path.join(_DATA, "customers.xlsx")

N = 26
SUR = list("王李张刘陈杨赵黄周吴徐孙马朱胡林何郭高罗郑梁谢宋唐许")
GIV = ["伟","芳","娜","秀英","敏","静","丽","强","磊","军","洋","勇","艳",
       "杰","娟","涛","明","超","秀兰","霞","平","刚","桂英","文","辉","红"]

status_pool = ["正常"] * 18 + ["已锁定"] * 5 + ["已冻结"] * 3
random.shuffle(status_pool)

cards, phones = set(), set()

def card4():
    while True:
        c = f"{random.randint(0, 9999):04d}"
        if c not in cards:
            cards.add(c); return c

def phone():
    while True:
        p = "1" + random.choice("3456789") + "".join(str(random.randint(0, 9)) for _ in range(9))
        if p not in phones:
            phones.add(p); return p

rows = [(SUR[i] + GIV[i], card4(), phone(), status_pool[i]) for i in range(N)]
df = pd.DataFrame(rows, columns=["姓名", "卡号后4位", "注册手机号", "账户状态"])
df.to_excel(OUT, index=False)

print(f"生成 {len(df)} 条客户记录 → {OUT}")
print(df.to_string(index=False))
