# 全系统精通指南（中文）

这是一份面向当前仓库真实状态的最完整学习文档。它不是营销文案，而是严格基于现有文档、代码和测试编写的系统掌握指南。

## 1. 核心事实

如果你只记住一句话，请记住这句：

`on-call-agent` 是一个 verifier-driven、durable、approval-gated 的事故响应运行时，也是
`On-Call Copilot` 当前的底层实现基础；今天它只有一条诚实、受边界约束的
`deployment-regression` 线上闭环路径。

如果你只记住三点，请记住：

1. 这个仓库强调的是运行时纪律，而不是能力广度。
2. 是否完成由 verifier 决定，而不是由模型口头宣称决定。
3. 今天唯一的线上写操作路径，是在显式审批后对本地 demo target 执行一次受边界约束的回滚。

## 2. 这个仓库是什么，不是什么

### 它是什么

- 一个基于 Python 3.11+ 的事故响应 harness，具有 typed tools、typed verifiers、
  checkpoints、transcripts、working memory 和 handoff artifacts。
- `On-Call Copilot` 当前产品方向的底层运行时。
- 一个先证明 resume、audit、verification、approval、handoff 边界，再考虑更大自动化范围的窄系统。
- 一个已经包含 operator shell、最小化 panel-first console、replay/eval 路径，以及一条 live
  deployment-regression 闭环的仓库。

### 它不是什么

- 不是 coding agent。
- 不是 generic chatbot。
- 不是 generic planner。
- 不是成熟的 ops 产品。
- 不是广义 autonomous remediation 平台。
- 不是 multi-agent 系统。
- 不是支持任意 incident family 和 action library 的通用 orchestration engine。

## 3. 产品视角 vs 运行时视角

这个仓库有两个都很重要的理解视角，混淆它们会导致错误描述。

### 产品视角

按照 `docs/product/PRODUCT_BRIEF.md`，`On-Call Copilot` 是：

- 一个面向 operator 的 incident decision and verification product
- 帮助 on-call engineer 查看当前状态、审查一个受边界约束的 mitigation candidate、
  验证它是否真的生效，并导出 handoff
- 有意保持狭窄且诚实，不夸大成熟度

它的产品价值不是“AI 能做 ops”，而是 decision compression：

- 现在发生了什么？
- 当前判断由哪些证据支持？
- 有没有受边界约束的 action candidate？
- 它是否需要审批？
- 恢复是否真的发生？
- 下一班 operator 能否安全接手？

### 运行时视角

今天更强的技术叙事其实是运行时本身。这个代码库是一个：

- 建立在窄 incident chain 之上的 verifier-driven state machine
- checkpoint + transcript 的 durable runtime
- 带有显式 permission provenance 的 approval-aware system
- 可 replay、可 inspect 的 harness

产品层是刻意做薄的。runtime truth 保存在 durable artifacts 中，而不是保存在 UI 状态或
assistant chat history 中。

### 实际理解规则

谈这个仓库时：

- 面向 operator 体验时用产品语言
- 面向实现真相时用运行时语言
- 永远不要让产品表述超出现有运行时行为

## 4. 当前范围快照

| 维度 | 当前真实状态 | 现在还不成立 |
| --- | --- | --- |
| Incident family | `deployment-regression` 是唯一 live family | 广泛的多 incident family 支持 |
| Live 写路径 | 仅支持回滚到 known-good version | 任意 remediation actions |
| Live target | `src/runtime/demo_target.py` 中的本地 demo HTTP 服务 | 真实生产集成 |
| 读路径 | 从 triage 到 action stub 的确定性链路 | 开放式 investigation planner |
| Operator surfaces | direct CLI、shell、console、session assistant | 成熟的多用户产品工作流 |
| 状态模型 | checkpoints、transcripts、working memory、handoff artifacts | 隐式 UI 状态驱动流程 |
| Autonomy | `manual`、`semi-auto`、fail-closed `auto-safe` | 广义 autonomous ops execution |
| Eval 范围 | 两条确定性 replay scenario | 广泛 benchmark harness |
| Skill system | 已有 repository skill asset loading，triage 会使用 | 大量 operational skills |
| 关键路径上的 LLM 依赖 | 当前 slice 不依赖 model-backed free-form runtime loop | 通用 LLM agent orchestration |

## 5. 仓库地图

### 顶层地图

| 路径 | 重要性 |
| --- | --- |
| `README.md` | 最好的短版项目定位与 quickstart |
| `AGENTS.md` | 仓库的架构和产品纪律约束 |
| `docs/architecture.md` | 运行时架构总结 |
| `docs/usage.md` | CLI、shell、console 命令参考 |
| `docs/demo.md` | 最快的 live demo 流程 |
| `docs/product/PRODUCT_BRIEF.md` | `On-Call Copilot` 的控制性产品规范 |
| `skills/incident-triage/SKILL.md` | 仓库内 skill metadata + instructions 的具体示例 |
| `src/` | 实际运行时代码 |
| `tests/` | 当前行为契约 |
| `evals/fixtures/` | 确定性 replay fixtures |
| `sessions/` | durable runtime outputs 与示例 |
| `docs/examples/deployment_regression_payload.json` | 标准 live demo 输入 payload |

### 按子系统划分的源码地图

| 子系统 | 关键文件 | 责任 |
| --- | --- | --- |
| Step chain | `src/agent/incident_*.py` | 显式 investigation 与 action-candidate slices |
| Live execution | `src/agent/deployment_rollback_execution.py`、`src/agent/deployment_outcome_verification.py` | 审批后的回滚与 post-action verification |
| Tools | `src/tools/implementations/*.py` | 确定性的 read/write tool 行为 |
| Verifiers | `src/verifiers/implementations/*.py` | 每个 slice 的 pass/fail 规则 |
| Context reconstruction | `src/context/session_artifacts.py` | 从 checkpoint 和 transcript 重建最新可用 artifacts |
| Handoff | `src/context/handoff*.py` | 组装、写入、再生成 operator handoff 输出 |
| Durable state | `src/memory/checkpoints.py`、`src/memory/incident_working_memory.py`、`src/transcripts/*.py` | checkpoints、working memory、append-only transcript 存储 |
| Permissions | `src/permissions/*.py` | allow/ask/deny policy 与 provenance |
| Shell | `src/runtime/shell.py` | 终端 operator workspace |
| Console | `src/runtime/console_api.py`、`src/runtime/console_server.py` | 基于 runtime truth 的薄 console |
| Assistant pane | `src/runtime/assistant_api.py` | 有边界的 session explainer，不是 workflow authority |
| Inspect/export | `src/runtime/inspect.py` | session、artifact、audit 与 export 视图 |
| CLI | `src/runtime/cli.py` | 命令行入口 |
| Live surface | `src/runtime/live_surface.py` | start incident、resolve approval、rerun verification |
| Replay/eval | `src/evals/incident_chain_replay.py`、`src/runtime/eval_surface.py` | 确定性 replay runner 与摘要 |
| Demo target | `src/runtime/demo_target.py` | 提供 `/deployment`、`/health`、`/metrics`、`/rollback` 的本地服务 |

## 6. 端到端事故链路

### 两条诚实路径

Replay 和 pre-approval runtime：

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub`

Live approved deployment-regression runtime：

`triage -> follow-up -> evidence -> hypothesis -> recommendation -> approval-gated action stub -> bounded rollback execution -> outcome verification`

### 按 slice 拆解

| 阶段 | 主文件 | Tool | Verifier | 成功 phase | Durable effect |
| --- | --- | --- | --- | --- | --- |
| Triage | `src/agent/incident_triage.py` | `incident_payload_summary` | `incident_triage_output` | `triage_completed` | 创建第一份 transcript 和 checkpoint |
| Follow-up | `src/agent/incident_follow_up.py` | `investigation_focus_selector` | `incident_follow_up_outcome` | `follow_up_investigation_selected` 或 `follow_up_complete_no_action` | 从 triage artifacts 恢复并选择一个目标，或安全 no-op |
| Evidence | `src/agent/incident_evidence.py` | `evidence_bundle_reader` | `incident_evidence_read_outcome` | `evidence_reading_completed` | 读取一份 live 或 fixture-backed evidence bundle |
| Hypothesis | `src/agent/incident_hypothesis.py` | `incident_hypothesis_builder` | `incident_hypothesis_outcome` | `hypothesis_supported` 或 `hypothesis_insufficient_evidence` | verifier 通过后写入第一份 `IncidentWorkingMemory` |
| Recommendation | `src/agent/incident_recommendation.py` | `incident_recommendation_builder` | `incident_recommendation_outcome` | `recommendation_supported` 或 `recommendation_conservative` | 用 recommendation 级别状态更新 `IncidentWorkingMemory` |
| Action stub | `src/agent/incident_action_stub.py` | `incident_action_stub_builder` | `incident_action_stub_outcome` | `action_stub_pending_approval` 或 `action_stub_not_actionable` | 写入 durable `approval_state` 边界 |
| Rollback execution | `src/agent/deployment_rollback_execution.py` | `deployment_rollback_executor` | `deployment_rollback_execution` | `action_execution_completed` | 仅在 recorded approval 后执行一次 bounded write |
| Outcome verification | `src/agent/deployment_outcome_verification.py` | `deployment_outcome_probe` | `deployment_outcome_verification` | `outcome_verification_succeeded` | 从外部 runtime state 验证恢复，并将 working memory 改写为 resolved state |

### 为什么这条链很重要

这不是一个 generic planner loop。每个 slice 都会：

1. 消费一个先前的 durable artifact
2. 产生 transcript events
3. 运行 verifier
4. 写入下一个 checkpointed phase

这是理解整个仓库的核心。

### 你必须熟悉的 phase 词汇

最重要的 phase：

- `triage_completed`
- `follow_up_investigation_selected`
- `follow_up_complete_no_action`
- `evidence_reading_completed`
- `hypothesis_supported`
- `hypothesis_insufficient_evidence`
- `recommendation_supported`
- `recommendation_conservative`
- `action_stub_pending_approval`
- `action_stub_not_actionable`
- `action_stub_approved`
- `action_stub_denied`
- `action_execution_completed`
- `outcome_verification_succeeded`

重要的 failure/deferred phases：

- `*_unverified`
- `*_failed_verification`
- `*_failed_artifacts`
- `evidence_reading_deferred`
- `hypothesis_deferred`
- `recommendation_deferred`
- `action_stub_deferred`
- `action_execution_deferred`

如果你看到一个 checkpoint phase 就能立刻解释它的操作含义，你就已经越过初学阶段了。

## 7. Runtime Truth 与状态模型

这个仓库采用了刻意分层的状态模型。

### 第 1 层：checkpoint control state

存储位置：

- `sessions/checkpoints/<session_id>.json`

定义位置：

- `src/memory/checkpoints.py`

它回答的问题：

- runtime 现在走到哪里了
- 当前 phase 是什么
- 当前 step 是多少
- approval 是 pending / approved / denied 吗
- 哪个 verifier 还在 pending
- 当前 requested/effective shell mode 是什么

关键字段：

- `current_phase`
- `current_step`
- `pending_verifier`
- `approval_state`
- `operator_shell`
- `summary_of_progress`

不该放在这里的内容：

- 完整执行历史
- 完整语义事故理解
- 作为 workflow authority 的 handoff prose

### 第 2 层：transcript execution truth

存储位置：

- `sessions/transcripts/<session_id>.jsonl`

定义位置：

- `src/transcripts/models.py`
- `src/transcripts/writer.py`

当前 event types：

- `resume_started`
- `model_step`
- `permission_decision`
- `tool_request`
- `tool_result`
- `verifier_result`
- `checkpoint_written`
- `approval_resolved`

它回答的问题：

- 实际发生了什么
- 顺序是什么
- 跑了哪些 tool / verifier 调用
- 是否存在缺失结果或结构化 failure

为什么 append-only 重要：

- 可 replay
- 可审计
- 事后分析可读
- 可以在不相信内存状态的前提下重建 artifacts

### 第 3 层：semantic incident memory

存储位置：

- `sessions/working_memory/<incident_id>.json`

定义位置：

- `src/memory/incident_working_memory.py`

当前作用：

- verifier-backed 的紧凑语义快照
- 在 verifier 通过的 `incident_hypothesis`、`incident_recommendation` 和成功的
  `deployment_outcome_verification` 后写入

典型内容：

- leading hypothesis snapshot
- unresolved gaps
- important evidence references
- recommendation snapshot
- compact handoff note

它不是什么：

- resume source of truth
- transcript 替代品
- project memory

### 第 4 层：derived handoff artifact

存储位置：

- `sessions/handoffs/<incident_id>.json`

定义位置：

- `src/context/handoff.py`
- `src/context/handoff_artifact.py`
- `src/context/handoff_regeneration.py`

它的角色：

- 从 durable runtime truth 推导出的稳定 operator-facing export

不是它的角色：

- workflow authority
- resume state

### `SessionArtifactContext`：最关键的重建接缝

定义位置：

- `src/context/session_artifacts.py`

这是整个仓库里最重要的文件之一。它负责：

- 一次性加载 checkpoint 和 transcript
- 重建 triage、follow-up、evidence、hypothesis、recommendation、action stub、
  action execution、outcome verification 的最新 typed outputs
- 暴露 verified vs latest 两类形式
- 以只读方式暴露 `IncidentWorkingMemory`
- 区分 availability、insufficiency 和 failure

如果你没有理解 `SessionArtifactContext`，你就还没有真正理解这个仓库。

### Insufficiency 与 synthetic failure 的区别

这个区分非常核心。

Insufficiency 表示：

- runtime 保守地认为“现在还不能继续”
- 例如：当前 phase 与后续 slice 不兼容
- 例如：verifier 尚未通过

Synthetic failure 表示：

- runtime 预期存在一条 durable artifact path，但发现它已经损坏
- 例如：有 tool request 但没有对应 tool result
- 例如：transcript 里的 output 无法通过 typed validation
- 例如：checkpoint 暗示应该存在 verifier-backed artifact，但 verifier result 缺失

Synthetic failure 定义在 `src/runtime/models.py`，并在 `src/runtime/execution.py` 中做统一规范化。

## 8. Operator Surfaces

所有 operator surfaces 都建立在同一份 runtime truth 之上。

### Direct CLI

`src/runtime/cli.py` 中的主要命令：

- `start-incident`
- `resolve-approval`
- `verify-outcome`
- `inspect-session`
- `inspect-artifacts`
- `show-audit`
- `export-handoff`
- `list-evals`
- `run-eval`
- `run-demo-target`
- `console`
- `shell`

CLI 是对 runtime seams 最薄的一层封装。

### Operator Shell

实现位置：

- `src/runtime/shell.py`

命令：

- `/sessions`
- `/new`
- `/resume`
- `/mode`
- `/status`
- `/inspect`
- `/audit`
- `/tail`
- `/why-not-auto`
- `/approve`
- `/deny`
- `/verify`
- `/handoff`

模式：

- `manual`
- `semi-auto`
- `auto-safe`

Shell 不会创建第二套 orchestration runtime。它调用的仍然是与 CLI 相同的 live surface、
inspection/export seams。

### Operator Console

实现位置：

- `src/runtime/console_api.py`
- `src/runtime/console_server.py`

核心事实：

- console 是 panel-first，不是 chat-first
- UI 展示 sessions、incident detail、timeline、approval、verification、handoff
- 它通过 `/api/phase1` 工作

### Session Assistant Pane

实现位置：

- `src/runtime/assistant_api.py`

它是一个有边界的 explainer，不是通用 agent：

- session-scoped
- 以 checkpoint、transcript、`SessionArtifactContext` 和 handoff state 为依据
- 不持久化 chat history
- 不会成为 workflow authority
- 遇到 generic planner prompt 会 fail closed

`tests/unit/test_runtime_assistant_api.py` 对这些边界有明确测试。

## 9. Live Deployment-Regression Path

### Demo target

live demo target 定义在 `src/runtime/demo_target.py`。

Endpoints：

- `GET /deployment`
- `GET /health`
- `GET /metrics`
- `POST /rollback`

初始 demo 状态：

- current version = bad version，默认 `2.1.0`
- previous version = known-good version，默认 `2.0.9`
- health 处于 degraded
- rollback 可用

回滚之后：

- current version 变成 previous version
- health 变为 healthy
- metrics 变好

### Live intake payload

标准示例见 `docs/examples/deployment_regression_payload.json`。

关键字段：

- `service_base_url`
- `expected_bad_version`
- `expected_previous_version`

正是这些字段让 live bounded rollback path 成为可能。

### Live path 的实际机制

1. `start-incident` 读取 payload，然后依次运行 triage、follow-up、evidence、hypothesis、
   recommendation、action stub。
2. 如果证据支持 deployment regression，session 会停在
   `action_stub_pending_approval`。
3. `resolve-approval --decision approve` 会先 durably 记录 approval，然后运行：
   - `DeploymentRollbackExecutionStep`
   - `DeploymentOutcomeVerificationStep`
4. `verify-outcome` 可以在之后再次触发 outcome verification。

### 有边界回滚实际检查什么

`src/tools/implementations/deployment_rollback.py` 中的 rollback tool 会校验：

- action stub type 必须是 `rollback_recent_deployment_candidate`
- live deployment 仍然报告 active bad release
- rollback 仍然可用
- live current version 仍然匹配 `expected_bad_version`
- live previous version 仍然匹配 `expected_previous_version`

这不是“执行任意 remediation”，而是一个高度受限的单写操作。

### Outcome verification 实际检查什么

`src/verifiers/implementations/deployment_outcome_probe.py` 中的 post-action verifier 要求：

- service 为 healthy
- `error_rate <= 0.05`
- `timeout_rate <= 0.05`
- 如果提供了 expected version，则 `current_version == expected_previous_version`

只有满足这些条件，phase 才会变成 `outcome_verification_succeeded`。

### `auto-safe` 是刻意做窄的

Shell 只有在以下条件全部满足时才会自动执行：

- `.oncall/settings.toml` 中 policy 已启用
- target base URL 在 allowlist 中
- session 正处于 pending approval boundary
- 已存在 verified hypothesis、recommendation 和 action stub
- hypothesis 是 supported deployment regression
- recommendation 是 `validate_recent_deployment`
- action stub 是 bounded rollback candidate
- incident working memory 存在
- 除 rollback 本身要清除的 validation gap 外，没有其他 blocking unresolved gaps
- live current version 匹配 expected bad version
- live previous version 匹配 expected known-good version
- live deployment endpoint 仍然报告 active bad release 且 rollback available
- rollback 尚未执行过

否则 `auto-safe` 会降级为 `semi-auto`，并把降级原因 durable 地写入 checkpoint。

## 10. 安全模型

### Tool risk model

定义在 `src/tools/models.py`：

- `read_only`
- `write`
- `dangerous`

### Permission policy

定义在 `src/permissions/policy.py`：

- read-only tools -> `allow`
- write tools -> `ask`
- dangerous tools -> `deny`

这个 policy 很简单，但会产出丰富的 provenance：

- policy source
- action category
- evaluated action type
- approval requirement
- approval reason 或 denial reason
- safety boundary
- future preconditions
- notes

### Approval model

Approval 持久化在 checkpoint 的 `approval_state` 中。

关键状态：

- `none`
- `pending`
- `approved`
- `denied`

一个重要点：

- action stub 记录的是 candidate 和 approval boundary
- candidacy 不等于 execution

### Post-approval 写操作语义

这里有一个很关键但容易忽略的细节：

- `deployment_rollback_executor` 仍然是一个被分类为 `ask` 的 write tool
- 在 approval 已经记录之后，runtime 会重写这条 permission record，用于解释：
  policy classification 仍然成立，但这不是一次新的审批请求

`tests/unit/test_runtime_inspect.py` 与
`tests/integration/test_live_deployment_regression_cli.py` 明确锁定了这一点。

### 保守行为是特性，不是缺陷

系统会在以下场景中刻意保持保守：

- 证据不足
- live service 已经在 known-good version 上恢复健康
- approval 被拒绝
- `auto-safe` gate 条件不满足
- 先前 durable artifacts 缺失或不一致

这是仓库可信度的一部分，而不是“能力不够”。

## 11. 关键代码走读

### 1. Intake 与第一个 durable slice

- `src/agent/incident_triage.py`

为什么重要：

- 它是特殊的第一个 slice
- 它会加载 `incident-triage` skill asset
- 它直接写入第一份 transcript 和 checkpoint

### 2. Resumable chain progression

- `src/agent/incident_follow_up.py`
- `src/agent/incident_evidence.py`
- `src/agent/incident_hypothesis.py`
- `src/agent/incident_recommendation.py`
- `src/agent/incident_action_stub.py`

为什么重要：

- 这些文件展示了仓库如何从 verified prior artifacts 恢复，而不是从隐藏的 memory 恢复

### 3. Shared harness 与 failure normalization

- `src/runtime/harness.py`
- `src/runtime/execution.py`
- `src/runtime/models.py`

为什么重要：

- 下游 slices 的公共 wiring 在这里
- tool/verifier failures 会被规范化为 synthetic failures
- 后续 slices 保持显式逻辑，同时共享机制被去重

### 4. Live execution seam

- `src/runtime/live_surface.py`
- `src/agent/deployment_rollback_execution.py`
- `src/agent/deployment_outcome_verification.py`

为什么重要：

- 这是唯一越过 approval boundary 的 live closed loop

### 5. Artifact reconstruction 与 handoff

- `src/context/session_artifacts.py`
- `src/context/handoff.py`
- `src/context/handoff_artifact.py`
- `src/context/handoff_regeneration.py`

为什么重要：

- 它们让 resume、inspection 和 handoff 在不创造第二状态层的前提下保持一致

### 6. Operator surfaces

- `src/runtime/inspect.py`
- `src/runtime/shell.py`
- `src/runtime/console_api.py`
- `src/runtime/console_server.py`
- `src/runtime/assistant_api.py`

为什么重要：

- 这些文件展示了产品层如何建立在 runtime truth 之上，而不是替代它

### 7. Tools 与 verifiers

建议成对阅读：

- `src/tools/implementations/incident_triage.py`
  配合 `src/verifiers/implementations/incident_triage.py`
- `src/tools/implementations/follow_up_investigation.py`
  配合 `src/verifiers/implementations/follow_up_investigation.py`
- `src/tools/implementations/evidence_reading.py`
  配合 `src/verifiers/implementations/evidence_reading.py`
- `src/tools/implementations/incident_hypothesis.py`
  配合 `src/verifiers/implementations/incident_hypothesis.py`
- `src/tools/implementations/incident_recommendation.py`
  配合 `src/verifiers/implementations/incident_recommendation.py`
- `src/tools/implementations/incident_action_stub.py`
  配合 `src/verifiers/implementations/incident_action_stub.py`
- `src/tools/implementations/deployment_rollback.py`
  配合 `src/verifiers/implementations/deployment_rollback_execution.py`
- `src/tools/implementations/deployment_outcome_probe.py`
  配合 `src/verifiers/implementations/deployment_outcome_probe.py`

这样读最能看出 verifier-driven architecture 的本质。

## 12. 如何运行、检查与验证

### 安装

```bash
python -m pip install -e '.[dev]'
```

如果入口命令不在当前 shell path 中，可使用：

```bash
.venv/bin/python -m runtime.cli <command> ...
```

### 运行 live demo

启动 demo target：

```bash
oncall-agent run-demo-target --port 8001
```

启动 incident：

```bash
oncall-agent start-incident \
  --family deployment-regression \
  --payload docs/examples/deployment_regression_payload.json \
  --json
```

审批回滚：

```bash
oncall-agent resolve-approval <session_id> --decision approve --json
```

重跑 verification：

```bash
oncall-agent verify-outcome <session_id> --json
```

导出 handoff：

```bash
oncall-agent export-handoff <session_id>
```

### 使用 shell

```bash
oncall-agent shell
```

推荐 live 流程：

```text
/sessions
/mode semi-auto
/new docs/examples/deployment_regression_payload.json
/status
/why-not-auto
/approve Rollback approved for the live demo target.
/verify
/handoff
```

### 使用 console

```bash
oncall-agent console
```

### 运行 replay/eval

Supported branch：

```bash
oncall-agent run-eval incident-chain-replay-recent-deployment --json
```

Conservative branch：

```bash
oncall-agent run-eval incident-chain-replay-insufficient-evidence --json
```

### 检查输出

Session 摘要：

```bash
oncall-agent inspect-session <session_id>
```

Artifact chain：

```bash
oncall-agent inspect-artifacts <session_id>
```

Audit trail：

```bash
oncall-agent show-audit <session_id> --event-type verifier_result --limit 5
```

### 记住文件输出位置

默认 live roots：

- `sessions/checkpoints/`
- `sessions/transcripts/`
- `sessions/working_memory/`
- `sessions/handoffs/`

默认 eval root：

- `sessions/evals/`

### 一次运行后最值得打开的文件

- session checkpoint JSON
- session transcript JSONL
- incident working memory JSON
- handoff JSON

如果你能顺着这四类 artifacts 把一个 session 讲明白，你对仓库的理解就已经很深了。

## 13. 测试证明了什么

### Live closed loop

- `tests/integration/test_live_deployment_regression_cli.py`

证明：

- start incident 会到达 `action_stub_pending_approval`
- approval 会触发 bounded rollback
- outcome verification 会成功
- working memory 会被改写为 resolved state
- post-approval 的 write permission 语义仍然诚实可审计

### Shell 行为

- `tests/integration/test_runtime_shell_cli.py`
- `tests/unit/test_runtime_shell.py`

证明：

- `semi-auto` 会到达 approval boundary
- `auto-safe` 只有在 allowlisted 且 enabled 时才能成功
- 否则 `auto-safe` 会 durably 降级
- `/new` 默认会创建 fresh session
- 已经健康的服务会进入 `action_stub_not_actionable`
- `/why-not-auto` 和 `/tail` 会清楚解释当前状态

### Console 与 assistant 边界

- `tests/integration/test_runtime_console_api.py`
- `tests/unit/test_runtime_console_server.py`
- `tests/unit/test_runtime_assistant_api.py`

证明：

- console 的 approve/deny 路径会反映真实 runtime truth
- console 可以导出 handoff 并展示 verification state
- UI 仍然保持 panel-first，assistant 保持 secondary
- assistant 是 grounded、session-scoped、non-persistent，并且会对 generic planner 请求 fail closed

### Artifact reconstruction 与 handoff

- `tests/integration/test_session_artifact_context.py`
- `tests/integration/test_handoff_context_assembly.py`
- `tests/integration/test_handoff_regeneration_flow.py`

证明：

- `SessionArtifactContext` 能重建最新 verified artifacts
- 缺失的 verifier/tool artifacts 会显式暴露为 synthetic failures
- handoff assembly 会遵守明确的优先级
- 缺失必要 artifacts 时 regeneration 会诚实失败

### Working memory 边界

- `tests/integration/test_incident_working_memory_flow.py`

证明：

- 第一份 working memory snapshot 在 hypothesis 阶段写入
- recommendation 会更新它
- failed recommendation 不会覆盖它
- 成功的 outcome verification 会清除 validation gap，并以 resolved state 重写 working memory

### 核心不变量

- `tests/unit/test_permission_policy.py`
- `tests/unit/test_action_approval_gate_contract.py`
- `tests/unit/test_runtime_execution.py`
- `tests/unit/test_resumable_slice_harness.py`

证明：

- 基于风险的 permission policy
- approval gate contract 一致性
- synthetic failure normalization
- shared harness 的 event 顺序与 checkpoint 行为

## 14. 当前限制

- 只有一个 live incident family：`deployment-regression`。
- 只有一个 write path：回滚到 previous known-good version。
- live target 是本地 demo HTTP 服务，不是真实 operational integration。
- replay/eval 范围刻意很窄，只覆盖 supported branch 与 conservative branch。
- assistant pane 是一个有边界的 deterministic explainer，不是 open-ended model-driven copilot。
- generic loop protocols 已存在，但还没有广义 generic loop runtime。
- project memory 与 cross-incident promotion 被有意推迟。
- console 是刻意做薄的本地界面。
- 这个仓库作为 runtime-engineering milestone 的强度，高于它作为 finished product 的强度。

这些不是偶然的缺失，而是明确的范围边界。

## 15. 面试表达方式

### 一个好的 30 秒介绍

“这个仓库是一个 verifier-driven、durable、approval-gated 的 Python 事故响应运行时。
它把一个窄 incident chain 从 triage 推进到 approval boundary，并且针对一条
deployment-regression live slice，可以在显式审批后执行一次 bounded rollback，再从外部
runtime state 验证恢复。它的重点不是广泛 autonomy，而是明确的 runtime truth：
checkpoints、append-only transcripts、artifact reconstruction、approval provenance 和
durable handoff。” 

### 你希望面试官清楚听到的点

- 这个项目的窄范围是刻意设计出来的
- progression 由 verification 决定
- durable artifacts 定义 truth
- approval 显式且可审计
- conservative behavior 是实现出来的，不只是文档口头描述
- 仓库会在不该扩展的地方诚实停下

### 最强的技术差异点

- `SessionArtifactContext`
- synthetic failure normalization
- checkpoint、transcript、working memory、handoff 的清晰分层
- post-approval bounded write semantics
- replay/eval 与 live path 的一致性

### 最该诚实承认的弱项

- 广度
- 真实集成
- 产品打磨
- 通用 autonomy

## 16. 推荐学习路径

1. 先读 `README.md`、`AGENTS.md`、`docs/architecture.md`、`docs/product/PRODUCT_BRIEF.md`。
   先建立仓库的 truth boundaries。
2. 再读 `docs/usage.md`、`docs/demo.md`、`docs/operator_shell_smoke_checklist.md`。
   先把 operator-facing flows 看清楚。
3. 打开 `docs/examples/deployment_regression_payload.json` 和 `src/runtime/demo_target.py`。
   把 live slice 具体化。
4. 按顺序读 step chain：
   `incident_triage.py`、`incident_follow_up.py`、`incident_evidence.py`、
   `incident_hypothesis.py`、`incident_recommendation.py`、`incident_action_stub.py`。
5. 再读 live post-approval path：
   `deployment_rollback_execution.py` 和 `deployment_outcome_verification.py`。
6. 每个 tool 与其 verifier 配对阅读。这样最容易看清 verifier-driven progression。
7. 阅读 `src/runtime/execution.py`、`src/runtime/harness.py`、`src/context/session_artifacts.py`。
   这里是 runtime spine。
8. 阅读 `src/memory/checkpoints.py`、`src/transcripts/models.py`、
   `src/memory/incident_working_memory.py`、`src/context/handoff*.py`。
   这里是 durable state model。
9. 阅读 `src/runtime/shell.py`、`src/runtime/console_api.py`、`src/runtime/assistant_api.py`、
   `src/runtime/inspect.py`。
   这里是 operator surface layer。
10. 运行两条 eval scenario 和一条 live demo session，然后直接打开生成出来的 checkpoint、
    transcript、working memory、handoff artifacts。
11. 阅读第 13 节列出的 integration tests。它们是最好的可执行 truth source。
12. 到这一步之后再读更长的 interview docs。那时它们会从抽象说明变成你已经能验证的事实。

## 17. 总结

这个仓库最适合被理解为一个已经完成的、范围刻意狭窄的 runtime milestone：

- verifier-driven
- durable
- approval-gated
- audit-friendly
- resumable
- 对自身边界保持诚实

它不是想证明模型能做所有事情。它真正想证明的是：它已经做的事情，在结构上是站得住脚的。
