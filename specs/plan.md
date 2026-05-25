# Implementation Plan: Hermes 领域级 DB MCP Server

**Workspace**: `hermes-db-mcp` | **Date**: 2026-05-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/hermes-db-mcp/spec.md`
**Depends-On**: `hermes-db-first`（Status: Done）

---

## Summary

构建一个独立的 Python MCP server，对外暴露领域语义化工具（create_topic / find_similar_topics 等），内部封装 embedding 生成、PG 读写、Redis 缓存更新、状态机校验。通过 stdio（本机调试）和 SSE（docker 内网）双模式提供服务。

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────┐
│  Hermes Agent (主编排)                                    │
│  - 不持有 DB 凭证                                         │
│  - 通过 MCP 协议调用领域工具                                │
└────────────────────┬────────────────────────────────────┘
                     │ stdio (本机) / SSE (docker proxy 网络)
                     ▼
┌─────────────────────────────────────────────────────────┐
│  hermes-db-mcp (本 feature)                              │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Tool Layer   │  │ Embedding    │  │ Cache Layer  │  │
│  │ (FastMCP)    │→ │ Service      │  │ (Redis)      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                  │                  │          │
│  ┌──────▼──────────────────▼──────────────────▼───────┐ │
│  │              Repository Layer (asyncpg)             │ │
│  └────────────────────────┬───────────────────────────┘ │
└───────────────────────────┼─────────────────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  shared-postgres (pgvector) │
              │  hermes schema             │
              └───────────────────────────┘
```

---

## Key Design Decisions

### Decision 1: FastMCP + 双模启动

- **背景**: 需要 stdio（本机 Claude Code 调试）和 SSE（docker 内网 agent 调用）两种传输
- **结论**: 使用 `mcp[server]` 的 `FastMCP` 类，通过 CLI 参数切换 transport
- **影响**: 一份代码，两种启动方式；SSE 模式基于 Starlette ASGI
- **来源**: https://github.com/modelcontextprotocol/python-sdk

### Decision 2: asyncpg 直连，不用 ORM

- **背景**: 表结构已固定（hermes-db-first），工具逻辑简单，ORM 增加复杂度无收益
- **结论**: asyncpg 连接池 + 参数化 SQL
- **影响**: SQL 写在 repository 层，类型安全靠 Pydantic model 保证
- **来源**: asyncpg 官方文档

### Decision 3: Embedding 通过 OpenAI 兼容 API

- **背景**: hermes-db-first 已决定用 OpenAI 兼容协议，支持 dashscope/OpenAI/Jina 等
- **结论**: 用 `httpx` 异步调用 `/v1/embeddings`，不依赖 openai SDK（减少依赖）
- **影响**: 轻量；失败时降级写入 NULL embedding + 入队标记

### Decision 4: Redis 缓存策略 — Write-Through

- **背景**: 写入时同步更新 Redis，读取时 Redis-first + PG fallback
- **结论**: 写入工具内部完成 PG + Redis 双写；读取工具先查 Redis，miss 则查 PG 并回填
- **影响**: 一致性强；Redis 不可用时降级为纯 PG 读写（不阻塞）

---

## Module Design

### Module: `server` — MCP 入口

**职责**: FastMCP 实例化、工具注册、transport 选择

**关键行为**:

```text
mcp = FastMCP("hermes-db", json_response=True)

启动逻辑:
  --transport stdio  → mcp.run(transport="stdio")
  --transport sse    → mcp.run(transport="sse", host="0.0.0.0", port=8080)
```

### Module: `tools/topics` — 选题工具集

**职责**: 5 个选题相关 MCP tool 的定义和参数校验

**关键接口**:

```text
@mcp.tool() create_topic(title, account, angle?, priority?, ...) → {id, status, embedding_pending, created_at}
@mcp.tool() find_similar_topics(text, account?, threshold=0.85, limit=5) → [{id, title, similarity, ...}]
@mcp.tool() update_topic_status(id, new_status) → {id, status, previous_status} | error
@mcp.tool() list_topics(account?, status?, limit=20, offset=0) → {items, total}
@mcp.tool() get_topic(id) → full record
```

### Module: `tools/inspirations` — 灵感工具集

**职责**: 4 个灵感相关 MCP tool

**关键接口**:

```text
@mcp.tool() create_novel_inspiration(content, book_id, category, title?, chapter_hint?) → {id, status, embedding_pending, created_at}
@mcp.tool() find_similar_inspirations(text, book_id?, category?, threshold=0.75, limit=5) → [{id, content, similarity, ...}]
@mcp.tool() list_inspirations(book_id, category?, limit=50, offset=0) → {items, total}
@mcp.tool() get_inspiration(id) → full record
```

### Module: `tools/health` — 健康检查

**职责**: 探活工具

```text
@mcp.tool() health() → {pg: "ok"|"error", redis: "ok"|"error", embedding: "ok"|"error"}
```

### Module: `services/embedding` — Embedding 服务

**职责**: 调用 OpenAI 兼容 API 生成向量

```text
async def generate_embedding(text: str) -> list[float] | None
  - 成功: 返回 1024 维向量
  - 失败: 返回 None（调用方降级处理）
  - 超时: 3s
```

### Module: `services/state_machine` — 状态机

**职责**: 校验状态流转合法性

```text
TOPIC_TRANSITIONS = {
    "draft": ["writing", "archived"],
    "writing": ["published", "archived"],
    "published": ["archived"],
    "archived": [],
}

INSPIRATION_TRANSITIONS = {
    "candidate": ["adopted", "archived"],
    "adopted": ["used", "archived"],
    "used": ["archived"],
    "archived": [],
}

def validate_transition(entity_type, current, target) -> bool | {error, allowed}
```

### Module: `repositories/topic_repo` — 选题数据访问

**职责**: asyncpg 参数化查询封装

```text
async def insert_topic(pool, data) -> UUID
async def find_similar(pool, embedding, account?, threshold, limit) -> list
async def update_status(pool, id, new_status) -> row
async def list_by_filter(pool, account?, status?, limit, offset) -> (items, total)
async def get_by_id(pool, id) -> row | None
```

### Module: `repositories/inspiration_repo` — 灵感数据访问

**职责**: 同上，针对 novel_inspirations 表

### Module: `services/cache` — Redis 缓存

**职责**: Write-through 缓存 + 读取回填

```text
async def cache_record(redis, key_pattern, id, data, ttl=7d)
async def get_cached(redis, key_pattern, id) -> dict | None
async def update_recent_set(redis, set_key, id, score=timestamp)
```

---

## Project Structure

```text
hermes-db-mcp/
├── pyproject.toml          # uv/pip 项目配置
├── Dockerfile
├── docker-compose.yml      # 生产部署（SSE 模式）
├── .env.example
├── src/
│   └── hermes_db_mcp/
│       ├── __init__.py
│       ├── server.py           # FastMCP 入口 + CLI
│       ├── config.py           # 环境变量配置 (pydantic-settings)
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── topics.py       # 选题工具
│       │   ├── inspirations.py # 灵感工具
│       │   └── health.py       # 健康检查
│       ├── services/
│       │   ├── __init__.py
│       │   ├── embedding.py    # Embedding API 调用
│       │   ├── cache.py        # Redis 缓存
│       │   └── state_machine.py
│       └── repositories/
│           ├── __init__.py
│           ├── topic_repo.py
│           └── inspiration_repo.py
├── tests/
│   ├── conftest.py
│   ├── test_topics.py
│   └── test_inspirations.py
└── README.md
```

---

## Dependencies

```text
核心:
  mcp[cli]          >= 1.12    # FastMCP + stdio/SSE transport
  asyncpg           >= 0.30    # PG 异步连接池
  redis[hiredis]    >= 5.0     # Redis 异步客户端
  httpx             >= 0.27    # Embedding API 调用
  pydantic-settings >= 2.0     # 环境变量配置
  pgvector          >= 0.3     # vector 类型序列化

开发:
  pytest + pytest-asyncio
  ruff
```

---

## Risks and Tradeoffs

| 风险 | 影响 | 缓解 |
|------|------|------|
| Embedding API 延迟/不可用 | create 工具变慢或降级 | 3s 超时 + NULL 降级 + embedding_pending 标记 |
| Redis 不可用 | 缓存失效，读取走 PG | Redis 操作 try/except，不阻塞主流程 |
| asyncpg 连接池耗尽 | 工具调用排队 | pool min=2, max=10；MCP 本身是串行调用，并发压力低 |
| 状态机规则变更 | 需改代码重部署 | 规则写在常量 dict，改动成本低 |
| Docker 网络隔离失效 | 外部可访问 MCP server | 不映射宿主机端口；compose 只声明 proxy 内网 |

---

## Verification Strategy

1. **单元测试**: 状态机、参数校验、embedding 降级逻辑（mock PG/Redis）
2. **集成测试**: 用 testcontainers 起 PG + Redis，验证完整 create → find_similar 流程
3. **MCP Inspector**: 用官方 `mcp dev` 工具交互式验证每个 tool 的输入输出
4. **端到端**: Hermes agent 配置 stdio 模式调用，验证真实场景

---

## Stage Readiness

- 是否需要 `data-model.md`：不需要（复用 hermes-db-first 的 data-model，无新实体）
- 下一步建议：`tasks`
- 阻塞项：无（hermes-db-first 已 Done）

---

## Notes

- 连接池生命周期跟随 MCP server 进程，启动时 create_pool，关闭时 close
- MCP 协议本身是请求-响应模式，不存在并发调用同一 server 的场景，连接池主要防止连接泄漏
- embedding_pending 标记的记录，后续可通过 cron 或独立 worker 补全，不在本 feature 范围内
- 项目用 `uv` 管理依赖（与 Hermes 保持一致）

---

## Sources

| 决策 | 来源 URL | 备注 |
|------|---------|------|
| FastMCP + transport | https://github.com/modelcontextprotocol/python-sdk | v1.12+ |
| asyncpg pool | https://magicstack.github.io/asyncpg/ | |
| pgvector Python | https://github.com/pgvector/pgvector-python | asyncpg 集成 |
| 参考架构 | https://github.com/Anarkh-Lee/universal-db-mcp | 借鉴双模启动模式 |
