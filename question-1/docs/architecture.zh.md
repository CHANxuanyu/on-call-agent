# 架构总览

返回主入口：[README.md](../README.md)

## 1. 一句话概览

`question-1` 是一个单体 FastAPI 应用：在同一进程里同时承载 v1 关键词搜索、v2 语义搜索和 v3 受限 Agent，并通过 startup 一次性完成文档加载、语义索引 warmup 与 catalog 生成。

## 2. 演进链路

项目从 v1 演进到 v3 的逻辑是递进的：

1. `v1`
   先把 HTML 变成干净、可搜索的可见文本
2. `v2`
   在 v1 基线上增加语义检索，解决 paraphrase / broad query
3. `v3`
   在 v2 之上增加“找文件 + 读文件 + 回答”的受限工作流

简化理解：

```text
v1: find the document
v2: find the right document even when wording drifts
v3: read the right document and answer with grounding
```

## 3. 启动流程

应用入口在 [app/main.py](../app/main.py)。

startup 期间会做四件事：

1. 加载 `data/*.html` 到 v1 `DocumentService`
2. 加载同一批 HTML 到 v2 `SemanticSearchService`
3. 执行 `semantic_service.warmup()`
4. 为 v3 调用 `AgentService.ensure_catalog()` 生成 `data/catalog.json`

流程图：

```text
data/*.html
  -> DocumentService (v1 lexical index)
  -> SemanticSearchService (v2 chunk + embeddings)
  -> AgentService.ensure_catalog() (v3 catalog.json)
  -> app ready
```

## 4. 请求路径

### v1 请求路径

```text
POST /v1/documents
  -> app/api/v1.py
  -> DocumentService.ingest_document(...)
  -> HTML parser
  -> tokenizer
  -> BM25 lexical index
```

```text
GET /v1/search
  -> app/api/v1.py
  -> DocumentService.search(...)
  -> BM25 lexical index
  -> JSON results
```

### v2 请求路径

```text
GET /v2/search
  -> app/api/v2.py
  -> SemanticSearchService.search(...)
  -> optional query rewrite
  -> semantic index search over chunks
  -> lexical fusion with v1 service
  -> doc aggregation
  -> JSON results
```

### v3 请求路径

```text
POST /v3/chat
  -> auth dependency
  -> rate-limit dependency
  -> AgentService.chat(...)
  -> AgentLoop or LLMAgentLoop
  -> readFile("catalog.json")
  -> select SOP file(s)
  -> readFile("sop-xxx.html")
  -> grounded answer
  -> tool_calls + consulted_files + history
```

```text
GET /v3/history/{session_id}
  -> auth dependency
  -> AgentService.get_history(...)
  -> in-memory session lookup
  -> history JSON
```

## 5. 主要模块职责

| 模块 | 目录 | 责任 |
| --- | --- | --- |
| API 层 | `app/api/` | 定义路由、校验请求、返回响应 |
| 核心模型 | `app/core/` | HTML 解析与 Pydantic schema |
| 数据存储 | `app/data_store/` | 内存文档存储 |
| 索引层 | `app/indexing/` | tokenizer、BM25、chunker、semantic index |
| 服务层 | `app/services/` | v1/v2/v3 的编排逻辑 |
| Agent 层 | `app/agent/` | v3 loop、tool、memory、prompting |
| 安全层 | `app/security/` | API key 鉴权与限流 |
| 观测层 | `app/observability/` | JSON 日志、metrics、request/trace middleware |

## 6. 数据与状态

当前版本的状态大多是内存态：

- v1 文档索引：内存中
- v2 语义索引：内存中
- v3 session：内存中
- `/v3/chat` 限流窗口：内存中

磁盘上的主要文件：

- `data/*.html`
- `data/catalog.json`

这意味着：

- 重启会丢失运行中写入的内存态 session 和限流状态
- v3 catalog 依赖 startup 重新生成

## 7. 安全边界

当前安全模型是“最小可用”而非“生产完备”：

- `POST /v1/documents`、`POST /v3/chat` 和 `GET /v3/history/{session_id}` 受 `API_KEY` 保护
- 客户端通过 `X-API-Key` 传值
- `/v3` 页面里的 `X-API-Key` 输入框填写的也是这个值，而不是 `OPENAI_API_KEY`
- 如果未配置 `API_KEY`，开发模式默认放行，但 startup 会打 warning
- `/v3/chat` 有简单的按 IP 限流
- `readFile(fname)` 禁止绝对路径和 path traversal

不受保护的端点：

- `/healthz`
- `/readyz`
- `/metrics`

## 8. 观测性

应用统一挂载了 `ObservabilityMiddleware`，因此具备：

- 自动生成或透传 `X-Request-ID`
- 自动生成或透传 `X-Trace-ID`
- JSON 日志
- Prometheus 指标
- `healthz` / `readyz`
- 对未处理异常统一返回 JSON

本地观测栈可通过 [docker-compose.observability.yml](../docker-compose.observability.yml) 启动：

- app
- Prometheus
- Grafana

## 9. 环境变量总览

最常用：

- `API_KEY`
- `RATE_LIMIT_PER_MIN`
- `OPENAI_API_KEY`
- `LOG_LEVEL`

v2 调参用：

- `V2_SCORE_EXPERIMENT_PRESET`
- `V2_QUERY_VARIANT_MERGE_STRATEGY`
- `V2_DISPLAY_SCORE_TEMPERATURE`
- `V2_FUSION_DENSE_WEIGHT`
- `V2_FUSION_LEXICAL_WEIGHT`

可复制样例见 [.env.example](../.env.example)。

## 10. 当前最重要的设计取舍

### 单体而不是拆服务

优点：

- 面试展示更直接
- 本地启动简单
- 跨阶段共享数据结构方便

代价：

- 状态都在一个进程里
- 更偏 demo / 作业型，而不是生产分布式架构

### 内存态而不是持久化

优点：

- 代码更短
- 更容易测试
- 更容易向评审解释

代价：

- 不适合真实高可用部署
- 重启后状态丢失

### 受限 Agent 而不是自由 Agent

优点：

- 行为可预测
- 安全边界清晰
- 测试稳定

代价：

- 扩展能力有限
- 依赖 catalog 质量

## 11. 下一步最合理的改造方向

1. 给文档、session、rate limit 增加持久化或共享存储
2. 让 v3 catalog 支持增量刷新
3. 把 per-process 限流升级为共享限流
4. 为 v2 增加离线评测与可替换向量后端
5. 为 v3 增加真实集成，而不是只停留在 `readFile`
