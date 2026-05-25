from uuid import UUID

from mcp.server.fastmcp import Context

from hermes_db_mcp.server import mcp, AppContext
from hermes_db_mcp.services.embedding import generate_embedding
from hermes_db_mcp.services.cache import cache_record, get_cached, update_recent_set
from hermes_db_mcp.repositories import inspiration_repo
from hermes_db_mcp.repositories.inspiration_repo import VALID_CATEGORIES


@mcp.tool()
async def create_novel_inspiration(
    content: str,
    book_id: str,
    category: str,
    ctx: Context,
    title: str | None = None,
    chapter_hint: str | None = None,
) -> dict:
    """创建小说灵感。自动生成 embedding 并写入 PG + Redis。"""
    app: AppContext = ctx.request_context.lifespan_context

    if not content:
        return {"error": "missing_required_field", "field": "content"}
    if not book_id:
        return {"error": "missing_required_field", "field": "book_id"}
    if not category:
        return {"error": "missing_required_field", "field": "category"}
    if category not in VALID_CATEGORIES:
        return {"error": "invalid_category", "field": "category", "allowed": sorted(VALID_CATEGORIES)}

    embed_text = f"{title} {content}" if title else content
    embedding = await generate_embedding(app.http, embed_text)

    row = await inspiration_repo.insert_inspiration(
        app.pool,
        content=content,
        book_id=book_id,
        category=category,
        title=title,
        chapter_hint=chapter_hint,
        embedding=embedding,
    )

    insp_id = str(row["id"])
    await update_recent_set(app.redis, f"hermes:novel:recent:{book_id}", insp_id)

    return {
        "id": insp_id,
        "status": row["status"],
        "embedding_pending": embedding is None,
        "created_at": str(row["created_at"]),
    }


@mcp.tool()
async def find_similar_inspirations(
    text: str,
    ctx: Context,
    book_id: str | None = None,
    category: str | None = None,
    threshold: float = 0.5,
    limit: int = 5,
) -> list[dict] | dict:
    """根据文本语义检索相似灵感。"""
    app: AppContext = ctx.request_context.lifespan_context

    embedding = await generate_embedding(app.http, text)
    if embedding is None:
        return {"error": "embedding_unavailable", "message": "无法生成查询向量"}

    rows = await inspiration_repo.find_similar(
        app.pool, embedding=embedding, book_id=book_id, category=category,
        threshold=threshold, limit=limit,
    )
    for r in rows:
        r["id"] = str(r["id"])
        r["similarity"] = round(r["similarity"], 4)
        r["created_at"] = str(r["created_at"])
    return rows


@mcp.tool()
async def list_inspirations(
    book_id: str,
    ctx: Context,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """列出灵感，按 book_id 过滤，可选 category。"""
    app: AppContext = ctx.request_context.lifespan_context

    items, total = await inspiration_repo.list_by_filter(
        app.pool, book_id=book_id, category=category, limit=limit, offset=offset,
    )
    for item in items:
        item["id"] = str(item["id"])
        item["created_at"] = str(item["created_at"])
    return {"items": items, "total": total}


@mcp.tool()
async def get_inspiration(id: str, ctx: Context) -> dict:
    """获取单条灵感详情，优先读 Redis 缓存。"""
    app: AppContext = ctx.request_context.lifespan_context

    cache_key = f"hermes:novel:{id}"
    cached = await get_cached(app.redis, cache_key)
    if cached:
        return cached

    inspiration_id = UUID(id)
    row = await inspiration_repo.get_by_id(app.pool, inspiration_id=inspiration_id)
    if not row:
        return {"error": "not_found", "id": id}

    result = {k: str(v) if k in ("id", "created_at", "updated_at") else v for k, v in row.items()}
    await cache_record(app.redis, cache_key, result)
    return result
