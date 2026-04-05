# On-Call Agent `question-1`

面向面试评审与新同学入门的操作手册。读完本文件，你应该可以在 10 到 15 分钟内完成以下事情：

- 创建虚拟环境并安装依赖
- 启动 FastAPI 服务并打开 `/v1`、`/v2`、`/v3`
- 用 `curl` 调用 v1、v2、v3 API
- 理解 v1 到 v3 的演进原因与设计取舍
- 跑通 `ruff` 与 `pytest`

英文版见 [README.en.md](./README.en.md)。

## Quickstart

1. 进入目录并创建虚拟环境

```bash
cd question-1
python3 -m venv .venv
source .venv/bin/activate
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

如果你想直接一键启动，也可以在安装依赖后执行：

```bash
./scripts/start.sh
```

3. 设置最小运行环境并启动服务

```bash
export API_KEY=dev-secret
export RATE_LIMIT_PER_MIN=30
uvicorn app.main:app --reload
```

4. 打开页面

- `http://127.0.0.1:8000/v1`
- `http://127.0.0.1:8000/v2`
- `http://127.0.0.1:8000/v3`
- `http://127.0.0.1:8000/docs`

5. 用另一终端做一分钟验证

```bash
curl http://127.0.0.1:8000/healthz
curl 'http://127.0.0.1:8000/v1/search?q=OOM'
curl 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{"message":"服务 OOM 了怎么办？"}'
```

6. 运行质量检查

```bash
ruff check .
pytest -q
```

也可以使用一键测试脚本：

```bash
./scripts/test.sh
./scripts/test.sh --smoke
```

## 目录

- [项目概览](#项目概览)
- [Feature Matrix](#feature-matrix)
- [仓库结构](#仓库结构)
- [环境要求](#环境要求)
- [安装依赖](#安装依赖)
- [本地启动](#本地启动)
- [一分钟快速验证](#一分钟快速验证)
- [浏览器页面与 API 示例](#浏览器页面与-api-示例)
- [Docker 与观测栈](#docker-与观测栈)
- [测试与质量检查](#测试与质量检查)
- [安全配置](#安全配置)
- [观测性说明](#观测性说明)
- [FAQ / Troubleshooting](#faq--troubleshooting)
- [Limitations & Next Steps](#limitations--next-steps)
- [设计文档导航](#设计文档导航)

## 项目概览

`question-1` 是一个分三阶段演进的 On-Call SOP 助手：

- `v1`：关键词搜索，解决“先把 SOP 找到”的问题
- `v2`：语义搜索，解决“用户表述和文档不完全一致”的问题
- `v3`：受限 Agent，对话式回答问题，并展示实际读取过的文件与工具调用轨迹
- `v3` 页面现在会渲染当前 session 的消息历史，并在需要时通过 `X-API-Key` 访问受保护的聊天接口

默认数据来自 [data/](./data)。应用启动时会自动：

- 加载 `data/*.html` 到 v1 词法索引
- 加载同一批文档到 v2 语义索引并做 warmup
- 为 v3 生成 [data/catalog.json](./data/catalog.json)

设计取舍很明确：

- 保持单体 FastAPI 应用，方便本地演示和面试评审
- 索引与会话默认在内存中，换取实现清晰度
- v3 默认走规则式 catalog-first 流程；只有设置 `OPENAI_API_KEY` 时才尝试 LLM loop

## Feature Matrix

| 维度 | v1 | v2 | v3 |
| --- | --- | --- | --- |
| 目标 | 关键词检索 | 语义检索 | 对话式 SOP 助手 |
| 路由前缀 | `/v1` | `/v2` | `/v3` |
| 主要接口 | `GET /v1/search`、`POST /v1/documents` | `GET /v2/search` | `POST /v3/chat`、`GET /v3/history/{session_id}` |
| 页面 | `GET /v1` | `GET /v2` | `GET /v3`（聊天页，含历史消息列表与 `X-API-Key` 输入） |
| 核心能力 | 可见文本抽取 + BM25 风格排序 | Chunk 级 embedding 检索 + lexical fusion | catalog-first 路由 + `readFile(fname)` + grounded answer |
| 典型查询 | `OOM`、`CDN`、`故障` | `服务器挂了`、`黑客攻击` | `数据库主从延迟超过30秒怎么处理？` |
| 是否需要精确词匹配 | 是 | 否 | 否 |
| 是否展示工具轨迹 | 否 | 否 | 是 |
| 受保护端点 | `POST /v1/documents` | 无 | `POST /v3/chat`、`GET /v3/history/{session_id}` |
| 鉴权方式 | `X-API-Key` | 无 | `X-API-Key` |
| 限流 | 无 | 无 | `/v3/chat` 按 IP 每分钟限流 |
| 会话能力 | 无 | 无 | 有，内存态 `session_id` + `history` 恢复 |
| 主要局限 | 依赖关键词命中 | 首次启动需要下载模型 | 无持久化，限流是 per-process |

## 仓库结构

```text
question-1/
├── app/
│   ├── api/                 # v1/v2/v3 路由
│   ├── agent/               # v3 agent loop、memory、tool、prompt
│   ├── core/                # HTML 解析与 Pydantic schema
│   ├── data_store/          # 内存文档存储
│   ├── indexing/            # tokenizer、BM25、chunker、semantic index
│   ├── observability/       # JSON 日志、metrics、request/trace middleware
│   ├── security/            # API key 鉴权、限流
│   ├── services/            # v1/v2/v3 服务层
│   └── main.py              # 应用入口与 startup wiring
├── data/                    # demo SOP 语料与 catalog.json
├── docs/                    # 中英文版本说明与架构文档
├── monitoring/              # Prometheus / Grafana provisioning / alert rules
├── static/                  # 前端 JS/CSS
├── templates/               # v1/v2/v3 页面模板
├── tests/                   # pytest 测试
├── Dockerfile
├── docker-compose.observability.yml
├── requirements.txt
└── ruff.toml
```

## 环境要求

- Python：建议 `3.11+`
- 系统：macOS / Linux / WSL 均可
- Docker：可选；如果你只想本地跑 Python，不需要 Docker
- 网络：首次运行 v2 时，`sentence-transformers` 可能需要下载模型

补充说明：

- 本地推荐 Python `3.11+`
- 提供的 [Dockerfile](./Dockerfile) 基于 `python:3.12-slim`
- `pytest` 默认使用 fake embedder / stub，不依赖真实 OpenAI，也不要求下载真实语义模型

## 安装依赖

在 `question-1/` 目录下执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果你希望使用 `.env.example` 里的值，可以先复制一份，再手动导出到当前 shell：

```bash
cp .env.example .env
set -a
source .env
set +a
```

注意：应用本身没有集成 `python-dotenv`。直接执行 `uvicorn` 时，`.env` 文件不会自动加载；你需要像上面这样显式 `source`，或者用 `export` 设置环境变量。

## 本地启动

最小启动命令：

```bash
export API_KEY=dev-secret
export RATE_LIMIT_PER_MIN=30
uvicorn app.main:app --reload
```

如果你不设置 `API_KEY`：

- 受保护端点在开发模式下默认放行
- 启动日志会输出 warning，提醒你生产环境必须设置 `API_KEY`

如果你设置 `OPENAI_API_KEY`：

- v3 会优先尝试 LLM loop
- 如果 OpenAI SDK 或运行时初始化失败，代码会回退到默认规则式 `AgentLoop`

```bash
export API_KEY=dev-secret
export RATE_LIMIT_PER_MIN=30
export OPENAI_API_KEY=''
uvicorn app.main:app --reload
```

启动完成后可访问：

- 页面：`/v1`、`/v2`、`/v3`
- 健康检查：`/healthz`
- 就绪检查：`/readyz`
- 指标：`/metrics`
- OpenAPI：`/docs`

## 一分钟快速验证

启动服务后，在另一终端执行：

```bash
curl http://127.0.0.1:8000/healthz
```

预期返回：

```json
{
  "status": "ok",
  "service": "On-Call Assistant",
  "version": "1.0.0"
}
```

然后验证三个版本：

```bash
curl 'http://127.0.0.1:8000/v1/search?q=OOM'
curl 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{"message":"数据库主从延迟超过30秒怎么处理？"}'
```

如果三条命令都能返回 JSON，说明：

- 服务已经起来了
- v1 词法索引可用
- v2 语义索引可用
- v3 chat、鉴权和限流依赖已生效

## 浏览器页面与 API 示例

### 浏览器页面

直接打开：

- `http://127.0.0.1:8000/v1`：关键词检索页面
- `http://127.0.0.1:8000/v2`：语义检索页面
- `http://127.0.0.1:8000/v3`：对话式 SOP 助手页面，包含历史消息列表、`X-API-Key` 输入框，以及最近一轮的 tool trace / consulted files 面板

### v1：导入文档与关键词搜索

写入接口在配置了 `API_KEY` 时需要 `X-API-Key`。

```bash
curl -X POST 'http://127.0.0.1:8000/v1/documents' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{
    "id": "sop-custom",
    "html": "<html><head><title>Custom SOP</title></head><body><p>Primary &amp; backup path is active.</p></body></html>"
  }'
```

响应示例：

```json
{
  "id": "sop-custom",
  "title": "Custom SOP"
}
```

搜索示例：

```bash
curl 'http://127.0.0.1:8000/v1/search?q=backup'
```

响应示例：

```json
{
  "query": "backup",
  "results": [
    {
      "id": "sop-custom",
      "title": "Custom SOP",
      "snippet": "Primary & backup path is active.",
      "score": 1.0
    }
  ]
}
```

### v2：语义搜索

```bash
curl 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl 'http://127.0.0.1:8000/v2/search?q=黑客攻击'
curl 'http://127.0.0.1:8000/v2/search?q=机器学习模型出问题'
```

响应示例：

```json
{
  "query": "黑客攻击",
  "results": [
    {
      "id": "sop-005",
      "title": "信息安全 On-Call SOP",
      "snippet": "怀疑系统被入侵时，立即隔离主机，保全证据，轮换高风险凭证，并上报安全事件。",
      "score": 0.87
    }
  ]
}
```

### v3：对话式 Agent

浏览器页面说明：

- `/v3` 是真正的聊天页，不只是单轮结果面板
- 页面会保留当前浏览器 session 里的 `session_id`，并通过 `GET /v3/history/{session_id}` 恢复历史消息
- 如果后端开启了 `API_KEY`，页面里的 `X-API-Key` 输入框要填写同一个值，例如 `dev-secret`
- 这里填写的是本项目服务自己的 API key，不是 `OPENAI_API_KEY`

首次提问：

```bash
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{
    "message": "服务 OOM 了怎么办？"
  }'
```

响应示例：

```json
{
  "session_id": "4db3e4b9-4d14-4c03-bf85-2f31dbf43b5d",
  "assistant_message": "结论\n服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。\n\n参考 SOP\n- sop-001.html",
  "tool_calls": [
    {
      "tool_name": "readFile",
      "arguments": {
        "fname": "catalog.json"
      },
      "status": "ok",
      "output_preview": "{\n  \"files\": ..."
    },
    {
      "tool_name": "readFile",
      "arguments": {
        "fname": "sop-001.html"
      },
      "status": "ok",
      "output_preview": "Title: 后端服务 On-Call SOP\nFile: sop-001.html\n..."
    }
  ],
  "consulted_files": [
    "sop-001.html"
  ],
  "history": [
    {
      "role": "user",
      "content": "服务 OOM 了怎么办？",
      "consulted_files": [],
      "tool_calls": []
    },
    {
      "role": "assistant",
      "content": "结论\\n服务 OOM 时，先检查实例内存使用、最近发布记录和降级开关，再确认是否存在异常流量或大对象缓存。\\n\\n参考 SOP\\n- sop-001.html",
      "consulted_files": [
        "sop-001.html"
      ],
      "tool_calls": [
        {
          "tool_name": "readFile",
          "arguments": {
            "fname": "catalog.json"
          },
          "status": "ok",
          "output_preview": "{\\n  \\\"files\\\": ..."
        }
      ]
    }
  ]
}
```

继续追问：

```bash
curl -X POST 'http://127.0.0.1:8000/v3/chat' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-secret' \
  -d '{
    "session_id": "4db3e4b9-4d14-4c03-bf85-2f31dbf43b5d",
    "message": "你刚才看了哪些文件？"
  }'
```

读取当前 session 的历史消息：

```bash
curl 'http://127.0.0.1:8000/v3/history/4db3e4b9-4d14-4c03-bf85-2f31dbf43b5d' \
  -H 'X-API-Key: dev-secret'
```

### 版本文档

- [v1 中文](./docs/v1.zh.md)
- [v1 English](./docs/v1.en.md)
- [v2 中文](./docs/v2.zh.md)
- [v2 English](./docs/v2.en.md)
- [v3 中文](./docs/v3.zh.md)
- [v3 English](./docs/v3.en.md)

## Docker 与观测栈

### 只启动应用容器

在 `question-1/` 目录下：

```bash
docker build -t on-call-agent-question-1 .
docker run --rm -p 8000:8000 \
  -e API_KEY=dev-secret \
  -e RATE_LIMIT_PER_MIN=30 \
  on-call-agent-question-1
```

### 启动应用 + Prometheus + Grafana

```bash
docker compose -f docker-compose.observability.yml up --build
```

默认端口：

- App：`http://127.0.0.1:8000`
- Prometheus：`http://127.0.0.1:9090`
- Grafana：`http://127.0.0.1:3000`

Grafana 默认账号密码：

- 用户名：`admin`
- 密码：`admin`

这是 demo 配置，仅用于本地演示，不适合生产。

## 测试与质量检查

### ruff

```bash
ruff check .
```

`ruff` 配置见 [ruff.toml](./ruff.toml)。

### pytest

```bash
pytest -q
```

如果你想把 `ruff`、`pytest` 和可选的 HTTP smoke test 串起来跑：

```bash
./scripts/test.sh
./scripts/test.sh --smoke
```

测试重点包括：

- v1 HTML 解析、可见文本抽取、重复写入替换语义
- v2 语义检索、hybrid fusion、startup warmup、query rewrite
- v3 tool trace、grounding、follow-up、聊天页历史恢复、低置信度处理
- 健康检查、metrics、request_id / trace_id
- API key 鉴权、`GET /v3/history/{session_id}` 和 `/v3/chat` 限流

### mypy

当前仓库没有配置 `mypy`，也没有把它纳入 CI。你不需要期待 `mypy` 命令在本仓库默认可用。

### CI

仓库根目录的最小 CI 在 [../.github/workflows/ci.yml](../.github/workflows/ci.yml)。本地建议至少执行与 CI 对齐的两条命令：

```bash
ruff check .
pytest -q
```

## 安全配置

可参考 [.env.example](./.env.example)。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `API_KEY` | 空 | 保护写接口、`POST /v3/chat` 与 `GET /v3/history/{session_id}` 的 API key |
| `RATE_LIMIT_PER_MIN` | `30` | `/v3/chat` 每个 `client_ip` 每分钟最大请求数 |
| `OPENAI_API_KEY` | 空 | 可选；设置后 v3 会尝试 LLM loop |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `V2_SCORE_EXPERIMENT_PRESET` | `baseline` | v2 分数实验预设 |
| `V2_QUERY_VARIANT_MERGE_STRATEGY` | `weighted_sum` | `weighted_sum` / `max_score` / `top2_avg` |
| `V2_DISPLAY_SCORE_TEMPERATURE` | `1.0` | v2 display score 温度 |
| `V2_FUSION_DENSE_WEIGHT` | `0.7` | v2 dense 权重 |
| `V2_FUSION_LEXICAL_WEIGHT` | `0.3` | v2 lexical 权重 |

当前受保护端点：

- `POST /v1/documents`
- `POST /v3/chat`
- `GET /v3/history/{session_id}`

不鉴权且不限流的端点：

- `GET /healthz`
- `GET /readyz`
- `GET /metrics`

注意事项：

- 如果 `API_KEY` 未设置，服务会进入开发模式并记录 warning
- 生产环境必须设置 `API_KEY`
- `/v3` 页面里的 `X-API-Key` 输入框填写的是这里的 `API_KEY`，不是 `OPENAI_API_KEY`
- 限流是进程内、按 `client_ip`、per-process 的简单滑动窗口实现
- 多进程 `uvicorn` 或多副本部署时，限流额度会按进程或副本分别计算

## 观测性说明

### 健康与就绪

- `/healthz`
  只回答“进程是否存活”
- `/readyz`
  回答应用是否完成 startup、文档加载、semantic warmup、catalog 生成

示例：

```bash
curl http://127.0.0.1:8000/readyz
```

响应示例：

```json
{
  "ready": true,
  "checks": {
    "startup": {
      "ready": true,
      "detail": "startup complete"
    },
    "catalog": {
      "ready": true,
      "detail": "catalog path: /app/data/catalog.json"
    },
    "document_index": {
      "ready": true,
      "detail": "10 HTML document(s) loaded"
    },
    "semantic_index": {
      "ready": true,
      "detail": "10 HTML document(s) indexed for semantic search"
    }
  }
}
```

### Metrics

```bash
curl http://127.0.0.1:8000/metrics
```

已暴露的指标包括：

- HTTP 请求总数与时延
- readiness 状态
- 未处理异常
- recommendation 质量分数
- dependency latency

### Request / Trace ID

如果你传入：

- `X-Request-ID`
- `X-Trace-ID`

中间件会把它们原样透传到响应头；如果不传，服务会自动生成。

## FAQ / Troubleshooting

### 1. 为什么服务启动后 `/readyz` 一开始是 `503`？

因为应用在 startup 阶段会加载 HTML 文档、构建 v2 语义索引、warmup 模型并生成 `catalog.json`。只要这些检查项还没全部 ready，`/readyz` 就会返回 `503`。这是预期行为。

### 2. 为什么第一次启动特别慢？

v2 依赖 `sentence-transformers`。第一次本地启动时，模型可能需要下载到缓存目录。Docker 构建也会因为 PyTorch CPU wheel 下载而比较慢。

### 3. 没有 `OPENAI_API_KEY`，v3 还能用吗？

可以。默认会使用规则式 `AgentLoop`。只有设置了 `OPENAI_API_KEY` 时，`AgentService` 才会优先尝试 `LLMAgentLoop`。

### 4. 为什么 `POST /v1/documents`、`POST /v3/chat` 或 `GET /v3/history/{session_id}` 返回 `401`？

说明你已经配置了 `API_KEY`，但请求没有带正确的 `X-API-Key`。请确认：

```bash
export API_KEY=dev-secret
curl -H 'X-API-Key: dev-secret' ...
```

如果你是在浏览器里用 `/v3` 页面：

- 页面输入框里填的是 `API_KEY`，例如 `dev-secret`
- 这里不是填 `OPENAI_API_KEY`

### 5. 为什么第二次调用 `/v3/chat` 就返回 `429`？

说明你触发了按 IP 的限流。检查 `RATE_LIMIT_PER_MIN` 是否被设置得过低，例如测试里常用 `1` 来验证限流逻辑。

### 6. 为什么我刚用 `POST /v1/documents` 导入的文档，v3 却看不到？

因为 v1 写入会立即更新 v1 和 v2 的内存索引，但不会自动刷新 v3 的 `catalog.json`。当前版本需要重启服务，startup 时重新生成 catalog。

### 7. 端口被占用了怎么办？

如果 `8000`、`9090` 或 `3000` 被占用，可以：

- 结束旧进程
- 或者在运行命令里改端口映射，例如 `uvicorn app.main:app --port 8001`
- Docker 场景下改 `-p 8001:8000`

### 8. 为什么本地 `pytest -q` 可以通过，但线上第一次运行 v2 还是慢？

因为测试默认使用 fake embedder / stub，不会真实下载模型，也不会请求 OpenAI。运行时的语义模型下载成本只出现在真实应用启动中。

### 9. 我已经创建了 `.env`，为什么直接 `uvicorn` 还是读不到变量？

因为仓库没有集成 `.env` 自动加载。你需要显式执行：

```bash
set -a
source .env
set +a
```

### 10. `/v3` 页面里的 `X-API-Key` 是做什么的？

它是这个项目服务自己的 API key，用来访问受保护的 `/v3/chat` 和 `/v3/history/{session_id}`。它不是 OpenAI 的 key。

- `X-API-Key` / `API_KEY`：本项目服务的门禁
- `OPENAI_API_KEY`：只有后端要调用 OpenAI 时才会使用

### 10. 我应该从哪个目录执行命令？

除非特别说明，本 README 里的命令都假设你当前位于 `question-1/` 目录下。

## Limitations & Next Steps

当前实现适合作为面试作品和本地 demo，不应直接视为生产级 on-call 平台。已知限制包括：

- 文档索引、session 和限流状态默认都在内存中
- `/v3/chat` 的限流是单进程、按 IP 的简单实现
- v3 只有一个工具 `readFile(fname)`，没有真实外部集成
- `POST /v1/documents` 不会自动刷新 v3 catalog
- 没有持久化存储、没有后台任务队列、没有多租户鉴权模型

下一步最值得做的事情：

1. 给文档、catalog、session 和 rate limit 引入持久化或共享状态
2. 为 v3 增加 catalog 增量刷新机制，而不是依赖重启
3. 把 per-process 限流升级为 Redis 或网关级限流
4. 增加真实 on-call 集成，例如 PagerDuty、Slack、工单系统
5. 为 v2 增加离线评估集、reranker 或可替换向量存储

## 设计文档导航

面向 onboarding 的双语版本说明：

- [架构总览（中文）](./docs/architecture.zh.md)
- [Architecture Overview (English)](./docs/architecture.en.md)
- [v1 中文](./docs/v1.zh.md)
- [v1 English](./docs/v1.en.md)
- [v2 中文](./docs/v2.zh.md)
- [v2 English](./docs/v2.en.md)
- [v3 中文](./docs/v3.zh.md)
- [v3 English](./docs/v3.en.md)

已有的技术设计深挖文档：

- [Phase 1 Technical Design](./docs/phase1.md)
- [Phase 2 Technical Design](./docs/phase2.md)
- [Phase 3 Technical Design](./docs/phase3.md)
