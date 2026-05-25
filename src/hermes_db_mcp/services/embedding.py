import httpx

from hermes_db_mcp.config import settings


async def generate_embedding(http: httpx.AsyncClient, text: str) -> list[float] | None:
    try:
        resp = await http.post(
            "/embeddings",
            json={
                "model": settings.embedding_model,
                "input": text,
                "dimensions": settings.embedding_dimension,
            },
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            timeout=3.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]
    except (httpx.HTTPError, KeyError, IndexError):
        return None
