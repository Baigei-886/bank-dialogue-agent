# Dify 编排导入说明

`dify/chatflow.yml` 是完整的 Chatflow 导出文件，包含全部 30 个节点、连线、提示词和参数。导入后有四处要手动配，都是环境相关的，配完就能跑。

## 导入

Dify 工作室 → 创建应用 → 导入 DSL → 选择 `dify/chatflow.yml`。

## 导入后要手动配的四处

**1. 模型**

编排里用的是通义千问（意图分类用轻量模型，业务节点用大参数模型）。如果你的 Dify 没配通义供应商，逐个打开 LLM 节点换成自己可用的模型即可，提示词不用动。

**2. 知识库**

导出文件里的知识库引用是原环境的 ID，导入后会失效。需要：
- 新建知识库，上传 `data/product_manual.txt`
- 打开「知识检索」节点，重新选中这个知识库

**3. HTTP 节点地址**

两个 HTTP 节点（核验、转账查询）指向本地数据服务：

```
http://host.docker.internal:8000/verify
http://host.docker.internal:8000/transfer
```

Dify 跑在 Docker 里时保持这个写法（容器内访问宿主机）；如果你的 Dify 直接跑在本机，改成 `http://localhost:8000/...`。启动数据服务：`python3 server/bank_api.py`。

**4. 发布**

改完点右上角发布。之后到「访问 API」页拿应用的 API Key，填进 `frontend/app.js` 的 `DIFY_KEY`。

## 验证跑通

发布后在预览里测三句：

| 输入 | 预期 |
|---|---|
| 你好 | 正常应答并引导业务 |
| 我的卡锁了 | 说明需要核验并弹出表单标记 |
| 卡锁了，我叫XX，卡号XXXX，手机1XXXXXXXXXX（用 data/customers.xlsx 里任一行） | 核验通过，按账户状态给处理方式 |

第三句能通，说明 HTTP 链路和数据服务都正常。
