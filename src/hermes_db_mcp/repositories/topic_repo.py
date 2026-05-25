from uuid import UUID

import asyncpg
from pgvector.asyncpg import register_vector


async def ensure_vector_type(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await register_vector(conn)


async def insert_topic(
    pool: asyncpg.Pool,
    *,
    title: str,
    account: str,
    angle: str | None = None,
    priority: str = "B",
    column_name: str | None = None,
    resonance: str | None = None,
    content: str | None = None,
    source: str = "topic-inbox",
    embedding: list[float] | None = None,
) -> dict:
    sql = """
        INSERT INTO hermes.topics (title, angle, account, priority, column_name, resonance, content, source, embedding)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id, status, created_at
    """
    async with pool.acquire() as conn:
        await register_vector(conn)
        row = await conn.fetchrow(
            sql, title, angle, account, priority, column_name, resonance, content, source, embedding,
        )
    return dict(row)


async def find_similar(
    pool: asyncpg.Pool,
    *,
    embedding: list[float],
    account: str | None = None,
    threshold: float = 0.85,
    limit: int = 5,
) -> list[dict]:
    conditions = ["embedding IS NOT NULL"]
    params: list = [embedding, threshold, limit]
    idx = 4

    if account:
        conditions.append(f"account = ${idx}")
        params.append(account)
        idx += 1

    where = " AND ".join(conditions)
    sql = f"""
        SELECT id, title, account, status, created_at,
               1 - (embedding <=> $1) AS similarity
        FROM hermes.topics
        WHERE {where} AND 1 - (embedding <=> $1) >= $2
        ORDER BY similarity DESC
        LIMIT $3
    """
    async with pool.acquire() as conn:
        await register_vector(conn)
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def update_status(pool: asyncpg.Pool, *, topic_id: UUID, new_status: str) -> dict | None:
    sql = """
        UPDATE hermes.topics SET status = $1 WHERE id = $2
        RETURNING id, status, updated_at
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, new_status, topic_id)
    return dict(row) if row else None


async def publish(pool: asyncpg.Pool, *, topic_id: UUID, published_url: str) -> dict | None:
    sql = """
        UPDATE hermes.topics SET status = 'published', published_url = $1 WHERE id = $2
        RETURNING id, status, published_url, updated_at
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, published_url, topic_id)
    return dict(row) if row else None


async def get_by_id(pool: asyncpg.Pool, *, topic_id: UUID) -> dict | None:
    sql = """
        SELECT id, title, angle, account, status, priority, column_name,
               resonance, content, source, published_url, created_at, updated_at
        FROM hermes.topics WHERE id = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, topic_id)
    return dict(row) if row else None


async def list_by_filter(
    pool: asyncpg.Pool,
    *,
    account: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conditions = []
    params: list = []
    idx = 1

    if account:
        conditions.append(f"account = ${idx}")
        params.append(account)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    count_sql = f"SELECT count(*) FROM hermes.topics {where}"
    list_sql = f"""
        SELECT id, title, angle, account, status, priority, created_at
        FROM hermes.topics {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params_with_pagination = params + [limit, offset]

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_sql, *params)
        rows = await conn.fetch(list_sql, *params_with_pagination)
    return [dict(r) for r in rows], total
