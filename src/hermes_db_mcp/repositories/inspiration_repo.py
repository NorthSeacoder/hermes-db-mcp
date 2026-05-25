from uuid import UUID

import asyncpg
from pgvector.asyncpg import register_vector


VALID_CATEGORIES = {"hook", "scene", "setting", "character", "conflict", "world", "plot"}


async def insert_inspiration(
    pool: asyncpg.Pool,
    *,
    content: str,
    book_id: str,
    category: str,
    title: str | None = None,
    chapter_hint: str | None = None,
    embedding: list[float] | None = None,
) -> dict:
    sql = """
        INSERT INTO hermes.novel_inspirations (content, book_id, category, title, chapter_hint, embedding)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, status, created_at
    """
    async with pool.acquire() as conn:
        await register_vector(conn)
        row = await conn.fetchrow(sql, content, book_id, category, title, chapter_hint, embedding)
    return dict(row)


async def find_similar(
    pool: asyncpg.Pool,
    *,
    embedding: list[float],
    book_id: str | None = None,
    category: str | None = None,
    threshold: float = 0.75,
    limit: int = 5,
) -> list[dict]:
    conditions = ["embedding IS NOT NULL"]
    params: list = [embedding, threshold, limit]
    idx = 4

    if book_id:
        conditions.append(f"book_id = ${idx}")
        params.append(book_id)
        idx += 1
    if category:
        conditions.append(f"category = ${idx}")
        params.append(category)
        idx += 1

    where = " AND ".join(conditions)
    sql = f"""
        SELECT id, content, book_id, category, status, created_at,
               1 - (embedding <=> $1) AS similarity
        FROM hermes.novel_inspirations
        WHERE {where} AND 1 - (embedding <=> $1) >= $2
        ORDER BY similarity DESC
        LIMIT $3
    """
    async with pool.acquire() as conn:
        await register_vector(conn)
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def get_by_id(pool: asyncpg.Pool, *, inspiration_id: UUID) -> dict | None:
    sql = """
        SELECT id, content, book_id, category, status, title, chapter_hint, created_at, updated_at
        FROM hermes.novel_inspirations WHERE id = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, inspiration_id)
    return dict(row) if row else None


async def list_by_filter(
    pool: asyncpg.Pool,
    *,
    book_id: str,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conditions = ["book_id = $1"]
    params: list = [book_id]
    idx = 2

    if category:
        conditions.append(f"category = ${idx}")
        params.append(category)
        idx += 1

    where = "WHERE " + " AND ".join(conditions)

    count_sql = f"SELECT count(*) FROM hermes.novel_inspirations {where}"
    list_sql = f"""
        SELECT id, content, book_id, category, status, title, created_at
        FROM hermes.novel_inspirations {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params_with_pagination = params + [limit, offset]

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_sql, *params)
        rows = await conn.fetch(list_sql, *params_with_pagination)
    return [dict(r) for r in rows], total
