# Feature Specification: Hermes 领域级 DB MCP Server

**Workspace**: `hermes-db-mcp`
**Created**: 2026-05-24
**Status**: Clarified
**Depends-On**: `hermes-db-first`（基础设施和数据模型先行）
**Input**: 用户描述: "把数据库写入封装成自建 MCP server，主 agent 通过领域级工具调用，不直接写 SQL；区别于 universal-db-mcp 的通用 SQL 执行器"

> 本 feature 不修改 `specs/.active`（保持 `hermes-db-first`），等 `hermes-db-first` 完成后再切换。

---

## Background

`hermes-db-first` 阶段建立了 PG（含 pgvector）+ Redis 基础设施和 `hermes` schema 的表结构，但写入路径仍是 Hermes agent 内部的 Python repository 类。当 skill 拆分为多个独立 agent 后，每个 agent 都要持有 DB 凭证、embedding 配置、SQL 知识，问题：

- 凭证分散，每个 agent 容器都要 mount 密码
- 业务规则（去重阈值、状态机）写在每个 skill 的 prompt 里，容易漂移
- 向量 SQL 语法 LLM 容易写错（`<=>` 操作符、cast 类型、HNSW 提示）
- prompt 注入风险——LLM 拼 SQL 在多 agent 场景下攻击面变大

通用方案如 `universal-db-mcp` 暴露的是 `execute_query`，仍然把 SQL 拼装和 embedding 生成留给调用方，没解决根本问题。

本 feature 把数据访问封装成领域级 MCP server，对外只暴露"语义化"工具（create_topic / find_similar_topics 等），server 内部完成 embedding 生成、SQL 拼装、状态校验、缓存更新。

---

## User Scenarios & Testing

### User Story 1 - 主 agent 通过领域工具入库选题 (Priority: P1)

作为 Hermes 主编排 agent，我希望调用 `create_topic` 这样的高层工具就能完成"生成 embedding + 写 PG + 更新 Redis + 返回 id"的完整流程，不需要懂 SQL 或 embedding API。

**Why this priority**: 这是 MCP server 存在的核心价值，所有后续工具都基于同一封装范式。

**Acceptance Scenarios**:

1. **[US1-1] 选题入库**
   **Given** MCP server 已配置 PG/Redis/embedding 连接
   **When** agent 调用 `create_topic(title="为什么程序员爱机械键盘", angle="情绪共鸣 + 工具党认同", account="月亮睡了")`
   **Then** 返回 `{id, status: "draft", created_at, similar_count: N}`，PG 中已写入含向量的记录，Redis `hermes:topics:recent:月亮睡了` 已更新

2. **[US1-2] embedding 失败降级**
   **Given** embedding API 不可达
   **When** agent 调用 `create_topic(...)`
   **Then** 仍写入 PG（embedding 列为 NULL），返回 `{id, embedding_pending: true}`，加入后台补全队列

3. **[US1-3] 必填字段校验**
   **Given** agent 传入 `create_topic(title="...")` 缺少 `account`
   **When** MCP server 收到调用
   **Then** 返回结构化错误 `{error: "missing_required_field", field: "account"}`，不写库

**Edge Cases**:

- **[US1-4]** 标题超过 200 字符 → 返回 `field_too_long` 错误，不截断不静默
- **[US1-5]** 同一 title 已存在 → 不视为错误，返回新 id（依赖语义去重 tool 而非唯一约束）

### User Story 2 - 语义去重检测 (Priority: P1)

作为主 agent，在写入前调用 `find_similar_topics` 拿到相似选题列表，由我决定是否提示用户"已有类似选题"，而不是 server 强行拒绝写入。

**Acceptance Scenarios**:

1. **[US2-1] 命中相似项**
   **Given** PG 中已有"程序员的键盘执念"选题
   **When** agent 调用 `find_similar_topics(text="为什么程序员爱机械键盘", threshold=0.85, limit=5)`
   **Then** 返回 `[{id, title, similarity: 0.91, account, status, created_at}, ...]` 按相似度倒序

2. **[US2-2] 无命中**
   **Given** 无相似选题
   **When** 调用 `find_similar_topics(...)`
   **Then** 返回 `[]`，agent 据此直接进入 create 流程

3. **[US2-3] 跨账号过滤**
   **Given** 调用时传入 `account="月亮睡了"`
   **When** server 执行检索
   **Then** 只返回该账号下的相似选题，避免跨账号干扰

### User Story 3 - 状态流转 (Priority: P1)

作为主 agent，我调用 `update_topic_status(id, "writing")` 时，server 应校验状态机合法性（draft→writing 允许，published→draft 拒绝）。

**Acceptance Scenarios**:

1. **[US3-1] 合法流转**
   **Given** 选题当前 status=draft
   **When** agent 调用 `update_topic_status(id, "writing")`
   **Then** 状态更新为 writing，返回 `{id, status: "writing", previous_status: "draft"}`

2. **[US3-2] 非法流转**
   **Given** 选题当前 status=published
   **When** agent 调用 `update_topic_status(id, "draft")`
   **Then** 返回 `{error: "invalid_transition", from: "published", to: "draft", allowed: ["archived"]}`

### User Story 4 - 小说灵感工具集 (Priority: P1)

镜像选题的工具集，针对 `novel_inspirations` 表。

**Acceptance Scenarios**:

1. **[US4-1]** `create_novel_inspiration(content, book_id, category, ...)` → 行为对齐 US1
2. **[US4-2]** `find_similar_inspirations(text, book_id?, category?, threshold, limit)` → 行为对齐 US2，多一层 book_id/category 过滤
3. **[US4-3]** `list_inspirations(book_id, category?, limit, offset)` → 结构化分页查询，不走向量

### User Story 5 - 凭证与权限隔离 (Priority: P1)

作为部署者，我希望 MCP server 是唯一持有 DB 密码的进程，主 agent 通过本地 stdio 或同网段 SSE 调用，不接触 PG 凭证。

**Acceptance Scenarios**:

1. **[US5-1]** Hermes agent 容器中**没有** `POSTGRES_PASSWORD` / `EMBEDDING_API_KEY`
2. **[US5-2]** MCP server 拒绝任何"裸 SQL"调用——没有 `execute_sql` 工具
3. **[US5-3]** MCP server 自身只允许同 docker 网络访问（无对外端口暴露）

### User Story 6 - 与 universal-db-mcp 共存 (Priority: P2)

作为开发者本人，我希望另外接一个只读的 universal-db-mcp 用于 ad-hoc 查询和数据探索，不参与 Hermes 主流程。

**Acceptance Scenarios**:

1. **[US6-1]** universal-db-mcp 用 read-only 凭证（`hermes_readonly_user`），与 hermes-db-mcp 完全隔离
2. **[US6-2]** Hermes 编排逻辑**不调用** universal-db-mcp，只调用本 feature 的领域工具

---

## Requirements

### Functional Requirements

- **FR-001**: MCP server 通过 stdio 和 SSE 双模式启动，stdio 给本机调试，SSE 给 docker 网络内 agent 调用
- **FR-002**: 工具集覆盖选题（create / find_similar / update_status / list / get）和灵感（create / find_similar / list / get）两个领域
- **FR-003**: 所有写入工具内部完成 embedding 生成；embedding 失败时降级写入 NULL 向量并入队补全
- **FR-004**: 所有相似度查询工具支持 `threshold` 和 `limit` 参数，按 cosine similarity 倒序返回
- **FR-005**: 状态流转工具内置状态机校验，非法流转返回结构化错误
- **FR-006**: server 启动时执行健康检查（PG ping、Redis ping、embedding API ping），任一失败则 fail-fast
- **FR-007**: server 配置全部通过环境变量注入：PG 连接、Redis 连接、embedding base_url/api_key/model
- **FR-008**: 所有工具调用记录结构化日志（tool name、参数 hash、耗时、结果状态），便于排查
- **FR-009**: 提供 `health` 工具供主 agent 主动探活

### Non-Functional Requirements

- **NFR-001**: 单次 `create_topic` 端到端 P95 < 1.5s（含 embedding API 往返）
- **NFR-002**: `find_similar_topics` 在 1 万条选题量级下 P95 < 200ms
- **NFR-003**: server 进程内存占用 < 256MB（小数据量场景）
- **NFR-004**: 所有 SQL 使用参数化查询，杜绝注入
- **NFR-005**: server 必须可被 docker compose 管理，重启策略 `unless-stopped`

### Key Entities

不引入新实体，复用 `hermes-db-first` 的 `hermes.topics` 和 `hermes.novel_inspirations` 表。

### Tool Surface（接口契约草案）

| Tool | 输入 | 输出 |
|------|------|------|
| `create_topic` | title, angle?, account, priority?, column_name?, resonance?, content?, source? | `{id, status, embedding_pending, created_at}` |
| `find_similar_topics` | text, account?, threshold=0.85, limit=5 | `[{id, title, similarity, account, status, created_at}]` |
| `update_topic_status` | id, new_status | `{id, status, previous_status}` 或 error |
| `list_topics` | account?, status?, limit=20, offset=0 | `{items, total}` |
| `get_topic` | id | full record |
| `create_novel_inspiration` | content, book_id, category, title?, chapter_hint? | `{id, status, embedding_pending, created_at}` |
| `find_similar_inspirations` | text, book_id?, category?, threshold=0.75, limit=5 | `[{id, content, similarity, book_id, category}]` |
| `list_inspirations` | book_id, category?, limit=50, offset=0 | `{items, total}` |
| `get_inspiration` | id | full record |
| `health` | - | `{pg, redis, embedding}` 三项状态 |

---

## Out of Scope

- 不提供通用 `execute_sql` 工具（这是与 universal-db-mcp 的根本差异）
- 不实现 daily-capture 相关工具（按 `hermes-db-first` 决定，daily 仍走文件）
- 不实现 OKR / 知识库 / 链接收藏相关工具（已有 StrideOS / nmem / Karakeep）
- 不做 embedding 模型微调或本地推理（embedding 全走 OpenAI 兼容 API）
- 不做 rerank（数据规模不需要）
- 不做 web 管理后台（数据探索用 universal-db-mcp 只读模式）

---

## Resolved Decisions (from Clarify)

- **D1 (语言 & 项目形态)**: 独立 repo + Python。理由：MCP server 是独立进程，有自己的 Dockerfile 和生命周期；Python `mcp` SDK 已支持 stdio + SSE；可复用 Hermes 侧 asyncpg 连接模式和 OpenAI embedding 调用逻辑；代码量预估 ~1000 行，独立 repo 维护成本低。
- **D2 (SSE 鉴权)**: 初期不加鉴权。只在 docker 内网 `proxy` 网络暴露，不映射宿主机端口。后续如需宿主机访问再加 bearer token。
- **D3 (历史数据迁移)**: 不放在本 feature。迁移脚本作为独立一次性工具，MCP server 只负责运行时。
- **D4 (delete 工具)**: 不提供 hard delete。仅通过 `update_*_status` 流转到 `archived`，数据只增不删。
- **D5 (参考实现)**: 参考 [universal-db-mcp](https://github.com/Anarkh-Lee/universal-db-mcp) 的 stdio/SSE 双模架构、连接池、健康检查模式，但只实现领域工具，不暴露通用 SQL。

---

## Stage Readiness

- 下一步建议：`plan`（所有关键歧义已解决）
- 阻塞项：本 feature 实施依赖 `hermes-db-first` 完成（PG schema、表结构已就绪，Status: Done）
- 当前状态：`hermes-db-first` 已完成，可直接推进 plan → tasks → implement
