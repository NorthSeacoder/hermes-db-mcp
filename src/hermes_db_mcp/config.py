from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    pg_dsn: str = "postgresql://hermes:password@localhost:5432/hermes"
    redis_url: str = "redis://localhost:6379/0"
    embedding_base_url: str = "http://new-api:3000/v1"
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    transport: str = "stdio"
    api_token: str = ""


settings = Settings()
