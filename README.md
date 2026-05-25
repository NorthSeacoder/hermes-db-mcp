# hermes-db-mcp

Hermes 领域级 DB MCP Server — 语义化数据访问工具。

对外暴露领域工具（create_topic / find_similar_topics 等），内部封装 embedding 生成、PG 读写、Redis 缓存、状态机校验。

## 工具列表

| Tool | 说明 |
|------|------|
| `health` | PG/Redis/Embedding 三项探活 |
| `create_topic` | 创建选题（自动 embedding + 缓存） |
| `find_similar_topics` | 语义相似选题检索 |
| `update_topic_status` | 状态流转（内置状态机） |
| `list_topics` | 列表查询（分页 + 过滤） |
| `get_topic` | 单条详情（缓存优先） |
| `create_novel_inspiration` | 创建灵感 |
| `find_similar_inspirations` | 语义相似灵感检索 |
| `list_inspirations` | 灵感列表 |
| `get_inspiration` | 灵感详情 |

## 本地开发（stdio 模式）

```bash
cp .env.example .env
# 编辑 .env 填入真实连接信息
uv sync
uv run hermes-db-mcp
```

## 部署（docker compose + SSE 模式）

```bash
cp .env.example .env
# 编辑 .env: TRANSPORT=sse, PG_DSN, REDIS_URL, EMBEDDING_*
docker compose up -d
```

Server 在 proxy 网络内监听 `8080` 端口，不映射宿主机端口。

## Hermes Agent 配置

在 Hermes agent 的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "hermes-db": {
      "url": "http://hermes-db-mcp:8080/sse"
    }
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PG_DSN` | - | PostgreSQL 连接串 |
| `REDIS_URL` | - | Redis 连接 URL |
| `EMBEDDING_BASE_URL` | - | OpenAI 兼容 embedding API |
| `EMBEDDING_API_KEY` | - | API Key |
| `EMBEDDING_MODEL` | text-embedding-v3 | 模型名 |
| `EMBEDDING_DIMENSION` | 1024 | 向量维度 |
| `TRANSPORT` | stdio | stdio 或 sse |
