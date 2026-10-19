# 电商小二 · 大模型驱动的电商智能客服

一个可以直接跑起来的完整项目，包含三个服务：

| 服务 | 目录 | 端口 | 作用 |
| --- | --- | --- | --- |
| 模拟电商中台 | `ecommerce-service-backend/` | 18081 | 提供订单、物流、商品、退款、催发货接口 |
| 智能客服后端 | `customer-service-backend/` | 18082 | 意图理解 → 流程编排 → 知识问答 → 回复 |
| 客服前端 | `customer-service-frontend/` | 5173 | Vue3 聊天界面，支持点击订单/商品卡片 |

> 想先看懂业务，直接读 [**业务知识点.md**](./业务知识点.md)，那里把每个设计点都对应到了具体代码。

---

## 一、环境要求

| 依赖 | 版本 | 本机情况 |
| --- | --- | --- |
| Python | 3.12+ | ✅ 3.13.14（项目内 `.venv`） |
| Node.js | 18+ | ⚠️ 未装进系统 PATH，通过 `NPM_CMD` 指向现有 node，见下 |
| 数据库 | MySQL 8.0 或 SQLite | ✅ 已切到本地 MySQL 8.0.44 |
| 大模型 | 阿里云百炼 DashScope Key | ✅ 已配置 |

**不需要 Docker。** 当前配置连接本机 MySQL（`commerce`、`customer_service` 两个库），
也支持一行配置切回 SQLite——两种数据库从第一天就都支持。

### Node.js 说明（前端需要）

本机没有把 Node.js 装进系统 PATH，`start_all.py` 会按下面的顺序找 npm：
环境变量 `NPM_CMD` → PATH → 常见安装目录 → 用 node 直接跑 npm 入口脚本。

PyCharm 的运行配置里已经带上了 `NPM_CMD`，所以在 IDE 里点运行能正常起前端。
如果你换终端手动跑 `start_all.py`，先设一下（Windows PowerShell）：

```powershell
$env:NPM_CMD = "C:\Users\LJF\.workbuddy\binaries\node\versions\22.22.2-6\npm.cmd"
```

**长期建议**：装一个官方 Node.js（<https://nodejs.org> 下 LTS 版），装完重开 PyCharm，
`NPM_CMD` 就可以删掉了。现在这种方式依赖工具自带的 node 目录，换机器会失效。

### 虚拟环境：全项目共用一个

两个后端统一使用项目根目录的 `.venv`，依赖合并写在根目录 `requirements.txt`，
**不需要**进到某个子目录再建环境。PyCharm 打开项目会自动识别它作为解释器。

环境已经装好，正常情况下直接跳到「二、启动」。换机器或环境损坏时才需要重建：

```bash
# 在项目根目录执行
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\pip.exe install -r requirements.txt
```

如果本机有 `uv`，两条命令更快：

```bash
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

---

## 二、启动（三步）

### 方式 A：一键启动（推荐）

在项目根目录双击或执行：

```bash
python start_all.py
```

它会依次启动中台、客服后端、前端，并等待依赖就绪。

### 方式 B：分开启动（便于看日志）

打开三个终端，每个终端都在项目根目录先执行一次激活：

```bash
.venv\Scripts\activate

# 终端 1 —— 模拟电商中台
cd ecommerce-service-backend
python -m uvicorn app.app:app --port 18081

# 终端 2 —— 智能客服后端
cd customer-service-backend
python main.py

# 终端 3 —— 前端（前端不用 Python 环境）
cd customer-service-frontend
npm run dev
```

打开 <http://127.0.0.1:5173> 即可对话。

接口文档：
- 客服后端 <http://127.0.0.1:18082/docs>
- 中台服务 <http://127.0.0.1:18081/docs>

---

## 三、验证跑通了没有

### 单元测试（不用起服务、不用联网）

```bash
.venv\Scripts\python.exe -m pytest customer-service-backend
```

47 个用例，0.2 秒跑完。覆盖五块最容易改坏的逻辑：

| 测试文件 | 钉住什么 |
| --- | --- |
| `tests/test_turn_planner_fallback.py` | 没 API Key 时的关键词兜底，以及「不要退款了」不能被识别成「又要退款」 |
| `tests/test_flow_executor.py` | 流程条件跳转、槽位收集、系统流程自愈、配置写错时安全收尾 |
| `tests/test_validator.py` | 六种「为什么这轮不能执行」的判定 |
| `tests/test_actions.py` | 退款 409 / 催发货 400 等错误怎么翻译成人话 |
| `tests/test_retrieval.py` | 中文 bigram 检索的打分与排序 |

### 端到端冒烟（要三个服务都起着）

```bash
.venv\Scripts\activate
cd customer-service-backend
python scripts\smoke_test.py
```

会依次跑 7 个场景：闲聊、查订单、查物流、知识问答、退款申请、催发货、点击订单卡片。

也可以直接看健康检查：

```bash
curl http://127.0.0.1:18082/health
# {"status":"ok","llm_model":"qwen-plus","llm_available":true,"commerce_api":"http://127.0.0.1:18081"}
```

`llm_available` 为 `true` 表示大模型接通了；为 `false` 时系统仍能跑，只是意图识别会退化成关键词规则。

### 静态检查

```bash
.venv\Scripts\ruff.exe check .          # 只检查
.venv\Scripts\ruff.exe check . --fix    # 自动修可修的
```

规则配在 `ruff.toml`，只开了 E/F/W/I/UP/B 这几组抓真实问题的规则，
行长、FastAPI 的 `Depends()` 默认参数等噪音规则已显式忽略。

---

## 四、演示数据

中台预置了 3 个用户、6 个商品、8 笔订单，覆盖了各种状态，方便测试不同分支：

| 订单号 | 商品 | 状态 | 适合演示 |
| --- | --- | --- | --- |
| `A20260410001` | iPhone 15 Pro | 待发货 | 查状态、退款、催发货 |
| `A20260408002` | 小米电热水壶 | 运输中 | 查物流（有完整轨迹） |
| `A20260407004` | Apple Watch S9 | 待揽收 | 催发货（允许） |
| `A20260405003` | 暖宝宝贴 | 已完成 | 已完成订单的话术 |
| `A20260402005` | 美的空气炸锅 | 已取消 | 异常状态兜底 |

可以这样试：

```
你：帮我查一下订单状态
助手：好的，我们先处理订单状态查询。请告诉我你的订单号。
你：A20260410001
助手：订单A20260410001当前状态是：待发货。商家正在备货，预计 24 小时内发出。
```

```
你：退款多久能到账
助手：（检索 FAQ + 规则文档后组织回答）
```

```
你：我要申请退款
助手：请告诉我你的订单号。
你：A20260410001
助手：请简单说一下退款原因。
你：买错了
助手：退款申请已提交，退款单号 R2026...，当前状态：submitted。
```

最后这条会在中台的 `refund_requests` 表里真实插入一条记录。

---

## 五、数据库与模型

### 当前状态：本地 MySQL

两个 `.env` 已指向 MySQL：

```ini
# ecommerce-service-backend/.env
DATABASE_URL=mysql+pymysql://root:***@127.0.0.1:3306/commerce?charset=utf8mb4

# customer-service-backend/.env
DATABASE_URL=mysql+aiomysql://root:***@127.0.0.1:3306/customer_service?charset=utf8mb4
```

`commerce` 库由 `switch_to_mysql.py` 建表并灌入演示数据；
`customer_service` 库只建库，`dialogue_states` 表由客服后端的 SQLAlchemy 模型在启动时自动创建。

### 重新切换到 MySQL（换机器 / 重建库）

```bash
python switch_to_mysql.py --password 你的MySQL密码
```

脚本会：测试连接 → 建两个库 → 重建 `commerce` 表并灌数据 → 改写两个 `.env`。
密码里有 `@`、`:` 等字符也没问题，脚本会做 URL 编码。

### 切回 SQLite（零安装）

把两个 `.env` 里的 `DATABASE_URL` 换成：

```ini
# 中台
DATABASE_URL=sqlite:///commerce.db

# 客服
DATABASE_URL=sqlite+aiosqlite:///./customer_service.db
```

中台首次需要播种：`cd ecommerce-service-backend && python seed_data.py`
（`seed_data.py` 会读 `DATABASE_URL`，指向 MySQL 时也能用，但会先清空表，慎用。）

### 换模型

改 `customer-service-backend/.env`：

```ini
LLM_MODEL=qwen-plus
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxx
```

任何 OpenAI 兼容接口都可以，比如 DeepSeek、Kimi、本地 vLLM。

### 没有 API Key 怎么办

把 `LLM_API_KEY` 留空即可。系统会自动走规则兜底，查订单、查物流、退款、催发货、常见规则问答仍然可用，只是理解自然语言的能力会变弱。

---

## 六、目录说明

```
ecommerce-cs/
├── .venv/                        # ★ 唯一虚拟环境，两个后端共用（PyCharm 会自动识别）
├── requirements.txt              # 两个后端的依赖合并在此
├── requirements-dev.txt          # 测试与静态检查依赖（pytest / pytest-asyncio / ruff）
├── ruff.toml                     # 静态检查规则
├── start_all.py                  # 一键启动
├── switch_to_mysql.py            # 切换到 MySQL（建库 + 灌数据 + 改配置）
├── 业务知识点.md                  # ★ 先读这个
├── README.md
├── db/                           # 建库脚本（commerce.sql / customer_service.sql）
│
├── ecommerce-service-backend/    # 模拟电商中台
│   ├── app/
│   │   ├── api.py                # 8 个业务接口
│   │   ├── models.py             # 8 张表
│   │   └── ...
│   └── seed_data.py              # 用 SQLite 时用它播种演示数据
│
├── customer-service-backend/     # 智能客服后端（核心）
│   ├── app/
│   │   ├── domain/               # 对话状态、消息模型
│   │   ├── planning/             # 意图理解（TurnPlanner）
│   │   ├── task/                 # 流程引擎（Flow / Command / Action）
│   │   ├── knowledge/            # 知识问答（API / FAQ / RAG）
│   │   ├── handlers/             # 三条轨道的入口
│   │   ├── engine/               # 总调度
│   │   ├── infrastructure/       # LLM、HTTP、提示词
│   │   ├── repositories/         # 状态持久化
│   │   └── services/             # 用例编排
│   ├── flow_config/              # ★ 业务流程配置（改这里就能加业务）
│   ├── knowledge_base/           # FAQ 与规则文档
│   ├── tests/                    # 单元测试（47 个，纯逻辑、不联网）
│   └── scripts/smoke_test.py     # 端到端冒烟测试
│
└── customer-service-frontend/    # Vue3 聊天界面
```

---

## 七、常见问题

**Q：浏览器报「无法访问此页面，127.0.0.1 拒绝连接」**
说明 5173 上没有进程在监听，前端没起来。按顺序查：
1. 运行窗口里 `前端` 那一行是 `[OK]` 还是 `[FAIL]`；
2. 如果是 `[FAIL]` 且提示没找到 npm，就是 Node.js 没装/没进 PATH，见「一、环境要求 → Node.js 说明」；
3. 如果提示端口被占用，是上一次没关干净，把残留的 node 进程结束再重试。

**Q：前端打开是白屏 / 接口 404**
确认三个服务都起来了，且端口没被占用：18081、18082、5173。

**Q：对话回复很慢**
每轮会调用一次大模型做意图理解，知识问答还会再调用一次生成回复，单轮约 2-5 秒，正常。

**Q：提示 `llm_available: false`**
`.env` 里的 `LLM_API_KEY` 为空或失效。填上 Key 后重启客服后端。

**Q：数据库乱了想重置**
- MySQL：重新跑 `python switch_to_mysql.py --password 你的密码`，它会重建 `commerce` 并灌回演示数据；
  想连对话历史一起清空，再执行 `DROP TABLE customer_service.dialogue_states`，重启客服后端会自动重建。
- SQLite：删掉 `ecommerce-service-backend/commerce.db` 后执行 `python seed_data.py`；
  删掉 `customer-service-backend/customer_service.db`，重启即自动重建。

**Q：为什么有代理还会请求失败**
项目里的本地 HTTP 客户端已显式关闭 `trust_env`，不会走系统代理。如果自己写脚本调本地接口，记得也加上这个参数。

**Q：语音播报按钮点了没反应**
`/api/chat/tts` 目前返回 501（未接入语音合成），前端会自动降级为纯文字。需要的话可在该接口里对接 DashScope CosyVoice。
