from uuid import UUID

from mcp.server.fastmcp import Context

from hermes_db_mcp.server import mcp, AppContext
from hermes_db_mcp.services.embedding import generate_embedding
from hermes_db_mcp.services.state_machine import validate_transition
from hermes_db_mcp.services.cache import cache_record, get_cached, update_recent_set
from hermes_db_mcp.repositories import topic_repo


@mcp.tool()
async def create_topic(
    title: str,
    account: str,
    ctx: Context,
    angle: str | None = None,
    priority: str = "B",
    column_name: str | None = None,
    resonance: str | None = None,
    content: str | None = None,
    source: str = "topic-inbox",
) -> dict:
    """创建选题。自动生成 embedding 并写入 PG + Redis。"""
    app: AppContext = ctx.request_context.lifespan_context

    if not title:
        return {"error": "missing_required_field", "field": "title"}
    if not account:
        return {"error": "missing_required_field", "field": "account"}
    if len(title) > 200:
        return {"error": "field_too_long", "field": "title", "max_length": 200}

    embed_text = f"{title} {angle}" if angle else title
    embedding = await generate_embedding(app.http, embed_text)

    row = await topic_repo.insert_topic(
        app.pool,
        title=title,
        account=account,
        angle=angle,
        priority=priority,
        column_name=column_name,
        resonance=resonance,
        content=content,
        source=source,
        embedding=embedding,
    )

    topic_id = str(row["id"])
    await update_recent_set(app.redis, f"hermes:topics:recent:{account}", topic_id)

    return {
        "id": topic_id,
        "status": row["status"],
        "embedding_pending": embedding is None,
        "created_at": str(row["created_at"]),
    }


@mcp.tool()
async def find_similar_topics(
    text: str,
    ctx: Context,
    account: str | None = None,
    threshold: float = 0.5,
    limit: int = 5,
) -> list[dict] | dict:
    """根据文本语义检索相似选题。"""
    app: AppContext = ctx.request_context.lifespan_context

    embedding = await generate_embedding(app.http, text)
    if embedding is None:
        return {"error": "embedding_unavailable", "message": "无法生成查询向量"}

    rows = await topic_repo.find_similar(
        app.pool, embedding=embedding, account=account, threshold=threshold, limit=limit,
    )
    for r in rows:
        r["id"] = str(r["id"])
        r["similarity"] = round(r["similarity"], 4)
        r["created_at"] = str(r["created_at"])
    return rows


@mcp.tool()
async def update_topic_status(id: str, new_status: str, ctx: Context) -> dict:
    """更新选题状态，内置状态机校验。"""
    app: AppContext = ctx.request_context.lifespan_context

    topic_id = UUID(id)
    current = await topic_repo.get_by_id(app.pool, topic_id=topic_id)
    if not current:
        return {"error": "not_found", "id": id}

    err = validate_transition("topic", current["status"], new_status)
    if err:
        return err

    row = await topic_repo.update_status(app.pool, topic_id=topic_id, new_status=new_status)
    await cache_record(app.redis, f"hermes:topic:{id}", {**current, "status": new_status})

    return {
        "id": id,
        "status": row["status"],
        "previous_status": current["status"],
    }


@mcp.tool()
async def publish_topic(id: str, published_url: str, ctx: Context) -> dict:
    """将选题标记为已发布，同时记录文章链接。仅 writing 状态可发布。"""
    app: AppContext = ctx.request_context.lifespan_context

    topic_id = UUID(id)
    current = await topic_repo.get_by_id(app.pool, topic_id=topic_id)
    if not current:
        return {"error": "not_found", "id": id}

    err = validate_transition("topic", current["status"], "published")
    if err:
        return err

    row = await topic_repo.publish(app.pool, topic_id=topic_id, published_url=published_url)
    await cache_record(app.redis, f"hermes:topic:{id}", {**current, "status": "published", "published_url": published_url})

    return {
        "id": id,
        "status": row["status"],
        "published_url": row["published_url"],
        "previous_status": current["status"],
    }


@mcp.tool()
async def list_topics(
    ctx: Context,
    account: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """列出选题，支持按账号和状态过滤。"""
    app: AppContext = ctx.request_context.lifespan_context

    items, total = await topic_repo.list_by_filter(
        app.pool, account=account, status=status, limit=limit, offset=offset,
    )
    for item in items:
        item["id"] = str(item["id"])
        item["created_at"] = str(item["created_at"])
    return {"items": items, "total": total}


@mcp.tool()
async def get_topic(id: str, ctx: Context) -> dict:
    """获取单条选题详情，优先读 Redis 缓存。"""
    app: AppContext = ctx.request_context.lifespan_context

    cache_key = f"hermes:topic:{id}"
    cached = await get_cached(app.redis, cache_key)
    if cached:
        return cached

    topic_id = UUID(id)
    row = await topic_repo.get_by_id(app.pool, topic_id=topic_id)
    if not row:
        return {"error": "not_found", "id": id}

    result = {k: str(v) if k in ("id", "created_at", "updated_at") else v for k, v in row.items()}
    await cache_record(app.redis, cache_key, result)
    return result
