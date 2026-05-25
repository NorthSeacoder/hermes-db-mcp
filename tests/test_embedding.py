import pytest
import httpx
import respx

from hermes_db_mcp.services.embedding import generate_embedding


@pytest.fixture
def mock_http():
    return httpx.AsyncClient(base_url="http://test-embedding:8080")


@pytest.mark.asyncio
class TestEmbedding:
    @respx.mock
    async def test_success(self, mock_http):
        fake_vector = [0.1] * 1024
        respx.post("http://test-embedding:8080/embeddings").respond(
            200, json={"data": [{"embedding": fake_vector}]}
        )
        result = await generate_embedding(mock_http, "test text")
        assert result == fake_vector

    @respx.mock
    async def test_timeout_returns_none(self, mock_http):
        respx.post("http://test-embedding:8080/embeddings").mock(
            side_effect=httpx.ReadTimeout("timeout")
        )
        result = await generate_embedding(mock_http, "test text")
        assert result is None

    @respx.mock
    async def test_server_error_returns_none(self, mock_http):
        respx.post("http://test-embedding:8080/embeddings").respond(500)
        result = await generate_embedding(mock_http, "test text")
        assert result is None

    @respx.mock
    async def test_malformed_response_returns_none(self, mock_http):
        respx.post("http://test-embedding:8080/embeddings").respond(
            200, json={"unexpected": "format"}
        )
        result = await generate_embedding(mock_http, "test text")
        assert result is None
