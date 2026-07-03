# -*- coding: utf-8 -*-
# 把 Dify 导出的 DSL 清洗后放进仓库。
# 用法：从 Dify 导出 yml 放到仓库根目录，然后运行
#   python3 scripts/sync_dsl.py 导出的文件.yml
# 脚本会：清洗品牌词/热线 → 校验 YAML 和敏感词 → 覆盖 dify/chatflow.yml → 删掉原文件
import io, os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DST = os.path.join(ROOT, "dify", "chatflow.yml")

REPS = [
    ("name: 农行客服agent", "name: 银行客服agent"),
    ("中国农业银行", "银行"),
    ("农业银行", "银行"),
    ("农行账号后4位", "银行账号后4位"),
    ("农行客服热线：95599 (7×24小时)", "客服热线 (7×24小时)"),
    ("拨打95599", "拨打客服热线"),
    ("拨95599", "拨打客服热线"),
    ("热线95599", "热线"),
    ("95599", "客服热线"),
    ("农行", "银行"),
    ("银行银行", "银行"),
]
FORBIDDEN = ["农行", "农业银行", "95599", "sk-", "api_key", "Bearer app-"]

def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/sync_dsl.py <导出的yml>")
        sys.exit(1)
    src = sys.argv[1]
    s = io.open(src, encoding="utf-8").read()
    for a, b in REPS:
        s = s.replace(a, b)

    # 校验
    import yaml
    d = yaml.safe_load(s)
    nodes = len(d["workflow"]["graph"]["nodes"])
    for w in FORBIDDEN:
        if w in s:
            print(f"仍有敏感词「{w}」，请检查后再同步"); sys.exit(1)

    io.open(DST, "w", encoding="utf-8").write(s)
    os.remove(src)
    print(f"已更新 {DST}（{nodes} 个节点），原文件已删除")
    print("接着执行：")
    print("  git add dify/chatflow.yml && git commit -m '更新编排' && git push")

if __name__ == "__main__":
    main()
