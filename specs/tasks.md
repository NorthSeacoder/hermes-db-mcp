# Tasks: Hermes 领域级 DB MCP Server

**Workspace**: `hermes-db-mcp` | **Date**: 2026-05-24
**Input**: `specs/hermes-db-mcp/spec.md` + `plan.md`
**Prerequisites**: spec.md ✅, plan.md ✅

---

## 执行原则

- 本 feature 产出一个独立 Python 项目（新 repo），不修改现有 note repo 代码
- 所有 SQL 使用参数化查询，禁止字符串拼接
- embedding 失败不阻塞写入，降级为 NULL + pending 标记
- Redis 不可用不阻塞主流程，降级为纯 PG
- 每个 Phase 结束后可独立验证，不依赖后续 Phase

---

## Phase 1: 项目骨架

**目标**: 建立可运行的空 MCP server，能通过 stdio 启动并响应 health 工具

- [ ] T101 初始化项目结构
  - scope: 新建 `hermes-db-mcp/` 项目，`uv init`，创建 `pyproject.toml`、`src/hermes_db_mcp/` 目录结构
  - action: 按 plan.md 的 Project Structure 创建目录和空文件；pyproject.toml 声明依赖（mcp[cli], asyncpg, redis, httpx, pydantic-settings, pgvector）
  - verify: `uv sync` 成功安装所有依赖

- [ ] T102 实现 config 模块
  - scope: `src/hermes_db_mcp/config.py`
  - action: 用 pydantic-settings 定义 `Settings` 类，读取环境变量：PG_DSN, REDIS_URL, EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSION(=1024), TRANSPORT(=stdio)
  - verify: 写 `.env.example`；`from hermes_db_mcp.config import Settings; Settings()` 不报错（有默认值或 .env）

- [ ] T103 实现 server 入口 + health 工具
  - scope: `src/hermes_db_mcp/server.py`, `src/hermes_db_mcp/tools/health.py`
  - action: FastMCP 实例化；注册 `health` 工具（暂时返回 mock 状态）；CLI 入口支持 `--transport stdio|sse`
  - verify: `uv run hermes-db-mcp --transport stdio` 启动后，用 `mcp dev` 或 MCP Inspector 调用 `health` 工具返回 `{pg: "mock", redis: "mock", embedding: "mock"}`

---

## Phase 2: 基础服务层

**目标**: 实现 PG 连接池、Redis 客户端、Embedding 服务，health 工具返回真实状态

- [ ] T201 实现 PG 连接池生命周期
  - scope: `src/hermes_db_mcp/server.py` (lifespan), `repositories/__init__.py`
  - action: server 启动时 `asyncpg.create_pool(dsn, min_size=2, max_size=10)`，关闭时 `pool.close()`；pool 通过 FastMCP context 或模块级变量传递给 tools
  - verify: 启动 server 连接到本地/远程 PG，`health` 工具中 `SELECT 1` 返回 pg: "ok"

- [ ] T202 实现 Redis 客户端生命周期
  - scope: `src/hermes_db_mcp/services/cache.py`
  - action: 启动时 `redis.asyncio.from_url()`，关闭时 `close()`；封装 `cache_record` / `get_cached` / `update_recent_set` 三个基础方法
  - verify: `health` 工具中 `PING` 返回 redis: "ok"

- [ ] T203 实现 Embedding 服务
  - scope: `src/hermes_db_mcp/services/embedding.py`
  - action: `httpx.AsyncClient` 调用 `{base_url}/v1/embeddings`，model/dimension 从 config 读取；3s 超时；失败返回 None
  - verify: `health` 工具中调用一次 embedding（短文本），成功返回 embedding: "ok"；断网时返回 embedding: "error"

- [ ] T204 health 工具接入真实检查
  - scope: `src/hermes_db_mcp/tools/health.py`
  - action: 替换 mock 为真实 PG ping + Redis ping + embedding ping
  - verify: MCP Inspector 调用 `health`，三项均返回真实状态

---

## Phase 3: 选题工具集

**目标**: 实现 5 个选题工具，覆盖 US1-US3 全部验收场景

- [ ] T301 实现状态机模块
  - scope: `src/hermes_db_mcp/services/state_machine.py`
  - action: 定义 TOPIC_TRANSITIONS / INSPIRATION_TRANSITIONS 常量 dict；`validate_transition(entity_type, current, target)` 返回 True 或结构化错误
  - verify: 单元测试覆盖合法/非法流转

- [ ] T302 实现 topic_repo
  - scope: `src/hermes_db_mcp/repositories/topic_repo.py`
  - action: 实现 `insert_topic`, `find_similar`, `update_status`, `list_by_filter`, `get_by_id` 五个异步函数；所有 SQL 参数化；向量查询用 `1 - (embedding <=> $1)` 计算 cosine similarity
  - verify: 集成测试（需要 PG + pgvector）

- [ ] T303 实现 create_topic 工具
  - scope: `src/hermes_db_mcp/tools/topics.py`
  - action: 参数校验（title 必填 ≤200 字符、account 必填）→ 生成 embedding（title + angle 拼接）→ insert_topic → 更新 Redis recent set → 返回 {id, status, embedding_pending, created_at}
  - verify: MCP Inspector 调用成功写入 PG；embedding 失败时 embedding_pending=true

- [ ] T304 实现 find_similar_topics 工具
  - scope: `src/hermes_db_mcp/tools/topics.py`
  - action: 生成查询文本 embedding → 调用 repo.find_similar（带 account 过滤、threshold、limit）→ 返回结果列表
  - verify: 写入两条相似选题后，find_similar 能返回 similarity > threshold 的结果

- [ ] T305 实现 update_topic_status 工具
  - scope: `src/hermes_db_mcp/tools/topics.py`
  - action: 查当前状态 → validate_transition → update → 返回 {id, status, previous_status} 或 error
  - verify: draft→writing 成功；published→draft 返回 invalid_transition 错误

- [ ] T306 实现 list_topics + get_topic 工具
  - scope: `src/hermes_db_mcp/tools/topics.py`
  - action: list 支持 account/status 过滤 + limit/offset 分页；get 先查 Redis 缓存，miss 查 PG 回填
  - verify: MCP Inspector 调用返回正确分页结构

---

## Phase 4: 灵感工具集

**目标**: 实现 4 个灵感工具，覆盖 US4 验收场景

- [ ] T401 实现 inspiration_repo
  - scope: `src/hermes_db_mcp/repositories/inspiration_repo.py`
  - action: 镜像 topic_repo 结构，针对 novel_inspirations 表；find_similar 多 book_id/category 过滤维度
  - verify: 集成测试

- [ ] T402 实现 create_novel_inspiration 工具
  - scope: `src/hermes_db_mcp/tools/inspirations.py`
  - action: 参数校验（content 必填、book_id 必填、category 必填且在枚举内）→ embedding → insert → Redis → 返回
  - verify: MCP Inspector 调用成功；category 非法值返回结构化错误

- [ ] T403 实现 find_similar_inspirations 工具
  - scope: `src/hermes_db_mcp/tools/inspirations.py`
  - action: 同 T304 模式，多 book_id/category 过滤
  - verify: 写入后能按 book_id 过滤检索

- [ ] T404 实现 list_inspirations + get_inspiration 工具
  - scope: `src/hermes_db_mcp/tools/inspirations.py`
  - action: 同 T306 模式
  - verify: 分页 + 缓存验证

---

## Phase 5: 容器化与部署

**目标**: 可通过 docker compose 在 NAS 上部署，Hermes agent 能通过 SSE 调用

- [ ] T501 编写 Dockerfile
  - scope: `hermes-db-mcp/Dockerfile`
  - action: 基于 `python:3.12-slim`；多阶段构建（builder 装依赖 + runtime 只拷贝）；ENTRYPOINT 默认 SSE 模式
  - verify: `docker build` 成功；`docker run` 启动后 health 可达

- [ ] T502 编写 docker-compose.yml
  - scope: `hermes-db-mcp/docker-compose.yml`
  - action: 声明 `proxy` 网络（external: true）；env_file 引用 `.env`；restart: unless-stopped；不映射宿主机端口
  - verify: `docker compose up -d` 后，从 proxy 网络内其他容器 `curl http://hermes-db-mcp:8080/sse` 可连接

- [ ] T503 Hermes agent 侧配置 MCP client
  - scope: Hermes agent 的 MCP 配置（不在本 repo，记录配置方式即可）
  - action: 在 README 中说明 Hermes 如何配置 SSE endpoint 连接本 server
  - verify: 文档清晰，包含示例配置

---

## Phase 6: 测试与收尾

**目标**: 确保质量和可维护性

- [ ] T601 编写单元测试
  - scope: `tests/`
  - action: 状态机测试、参数校验测试、embedding 降级测试（mock 外部依赖）
  - verify: `uv run pytest` 全绿

- [ ] T602 编写集成测试
  - scope: `tests/`
  - action: 用 docker compose 起 PG + Redis，测试完整 create → find_similar → update_status 流程
  - verify: CI 或本地 `docker compose -f docker-compose.test.yml up` + `pytest` 全绿

- [ ] T603 编写 README
  - scope: `hermes-db-mcp/README.md`
  - action: 项目说明、本地开发（stdio 模式）、部署（docker compose）、工具列表、环境变量说明
  - verify: 新人读完能独立启动和调试

- [ ] T604 端到端验证
  - scope: 完整链路
  - action: NAS 部署后，Hermes agent 通过 SSE 调用 create_topic → find_similar_topics → update_topic_status 完整流程
  - verify: 数据正确写入 PG + Redis；状态机拦截非法流转；embedding 向量可检索

---

## 依赖与顺序

```text
Phase 1 (骨架) → Phase 2 (服务层) → Phase 3 (选题) ──┐
                                    → Phase 4 (灵感) ──┼→ Phase 5 (部署) → Phase 6 (测试收尾)
                                                       │
Phase 3 与 Phase 4 可并行（无交叉依赖）─────────────────┘
```

- **关键路径**: T101 → T102 → T103 → T201 → T203 → T302 → T303 → T501 → T604
- **可并行**: Phase 3 与 Phase 4 互不依赖；T601 可在 Phase 3/4 完成后立即开始
- **强阻塞**: T201（PG 连接池）必须先于所有 repo 任务；T203（embedding）必须先于所有 create/find_similar 任务

---

## 覆盖检查

| 场景 / 需求 | 对应任务 |
|-------------|----------|
| US1 选题入库 | T302, T303 |
| US1-2 embedding 失败降级 | T203, T303 |
| US1-3 必填字段校验 | T303 |
| US2 语义去重 | T304 |
| US2-3 跨账号过滤 | T304 |
| US3 状态流转 | T301, T305 |
| US4 小说灵感工具集 | T401-T404 |
| US5 凭证隔离 | T502 (不映射端口, env 隔离) |
| US6 与 universal-db-mcp 共存 | 架构天然隔离，无需额外任务 |
| FR-001 stdio + SSE 双模 | T103, T501 |
| FR-006 启动健康检查 | T204 |
| FR-008 结构化日志 | T103 (FastMCP 内置 logging) |
| NFR-004 参数化查询 | T302, T401 |
| NFR-005 docker compose 管理 | T502 |

---

## Notes

- 新项目位置建议：与 Hermes 同级目录，或用户指定的位置（实现时确认）
- Phase 1-2 预计 1-2 小时可完成（代码量小，模式固定）
- Phase 3-4 是核心工作量，预计各 1-2 小时
- Phase 5-6 依赖 NAS 环境，可能需要分次完成
- 如果用户希望先在本地跑通 stdio 模式再部署，可以 Phase 1-4 先做，Phase 5 后补

---

## Stage Readiness

- 推荐下一步：`implement`（任务粒度已足够，每个任务都是具体的代码/配置操作）
- 阻塞项：需确认新项目创建位置
- 建议节奏：按 Phase 顺序推进，Phase 1-2 一气呵成，Phase 3/4 可并行
