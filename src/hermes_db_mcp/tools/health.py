from mcp.server.fastmcp import Context

from hermes_db_mcp.server import mcp, AppContext
from hermes_db_mcp.config import settings


@mcp.tool()
async def health(ctx: Context) -> dict:
    """检查 PG、Redis、Embedding 三项服务的连接状态。"""
    app: AppContext = ctx.request_context.lifespan_context
    result = {}

    # PG
    try:
        await app.pool.fetchval("SELECT 1")
        result["pg"] = "ok"
    except Exception as e:
        result["pg"] = f"error: {e}"

    # Redis
    try:
        await app.redis.ping()
        result["redis"] = "ok"
    except Exception as e:
        result["redis"] = f"error: {e}"

    # Embedding
    try:
        resp = await app.http.post(
            "/embeddings",
            json={"model": settings.embedding_model, "input": "ping", "dimensions": settings.embedding_dimension},
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            timeout=3.0,
        )
        resp.raise_for_status()
        result["embedding"] = "ok"
    except Exception as e:
        result["embedding"] = f"error: {e}"

    return result
