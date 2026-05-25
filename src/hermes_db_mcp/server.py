from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncpg
import redis.asyncio as aioredis
import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

from hermes_db_mcp.config import settings
from hermes_db_mcp.middleware import BearerAuthMiddleware


@dataclass
class AppContext:
    pool: asyncpg.Pool
    redis: aioredis.Redis
    http: httpx.AsyncClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    pool = await asyncpg.create_pool(settings.pg_dsn, min_size=2, max_size=10)
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    http_client = httpx.AsyncClient(
        base_url=settings.embedding_base_url,
        timeout=httpx.Timeout(10.0, connect=3.0),
    )
    try:
        yield AppContext(pool=pool, redis=redis_client, http=http_client)
    finally:
        await http_client.aclose()
        await redis_client.aclose()
        await pool.close()


mcp = FastMCP(
    "hermes-db",
    json_response=True,
    lifespan=app_lifespan,
    host="0.0.0.0",
    port=8080,
)


def register_tools():
    from hermes_db_mcp.tools import health  # noqa: F401
    from hermes_db_mcp.tools import topics  # noqa: F401
    from hermes_db_mcp.tools import inspirations  # noqa: F401


def main():
    register_tools()
    transport = settings.transport
    if transport == "sse":
        app = Starlette(routes=[Mount("/", app=mcp.sse_app())])
        app = BearerAuthMiddleware(app)
        uvicorn.run(app, host="0.0.0.0", port=8080)
    elif transport == "streamable-http":
        app = BearerAuthMiddleware(mcp.streamable_http_app())
        uvicorn.run(app, host="0.0.0.0", port=8080)
    else:
        mcp.run(transport=transport)


if __name__ == "__main__":
    main()
