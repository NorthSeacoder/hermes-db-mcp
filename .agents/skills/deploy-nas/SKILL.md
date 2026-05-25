# Deploy to NAS

将 hermes-db-mcp 部署/更新到 NAS 的操作流程。

## 前置条件

- 代码已推送到 GitHub 并打了 `v*` tag
- GitHub Actions 构建完成（ghcr.io 镜像已就绪）
- NAS 可通过 `ssh nas` 访问

## 部署步骤

```bash
# 1. 拉取最新镜像并重启
rtk ssh nas "cd /vol1/1000/Docker/hermes-db-mcp && docker compose pull && docker compose up -d"

# 2. 验证容器状态
rtk ssh nas "docker logs hermes-db-mcp 2>&1 | tail -5"
```

预期输出：
```
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

## 健康检查

```bash
# 容器内网 IP（proxy 网络）
rtk ssh nas "docker inspect hermes-db-mcp --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'"

# SSE 端点连通性
rtk ssh nas "curl -s -m 3 http://<IP>:8080/sse"
```

## 配置文件位置

- compose: `/vol1/1000/Docker/hermes-db-mcp/docker-compose.yml`
- 环境变量: `/vol1/1000/Docker/hermes-db-mcp/.env`

## 环境变量说明

| 变量 | 用途 |
|------|------|
| PG_DSN | PostgreSQL 连接串（含 schema search_path） |
| REDIS_URL | Redis 连接串（含密码） |
| EMBEDDING_BASE_URL | New API embedding 端点 |
| EMBEDDING_API_KEY | New API token |
| EMBEDDING_MODEL | 模型名（BAAI/bge-m3） |
| EMBEDDING_DIMENSION | 向量维度（1024） |
| TRANSPORT | 传输模式（sse） |

## 回滚

```bash
# 回滚到指定版本
rtk ssh nas "cd /vol1/1000/Docker/hermes-db-mcp && \
  sed -i 's|:latest|:v0.1.0|' docker-compose.yml && \
  docker compose pull && docker compose up -d"
```

## 发版流程（完整）

```bash
# 本地
git tag v0.x.x
git push origin v0.x.x
# 等待 GitHub Actions 完成（约 2-3 分钟）

# NAS
rtk ssh nas "cd /vol1/1000/Docker/hermes-db-mcp && docker compose pull && docker compose up -d"
```
