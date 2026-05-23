"""Bob Manager Control Plane — Configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql+asyncpg://bobmanager:changeme_in_production@bob-db:5432/bobmanager"

    # Security
    agent_secret: str = "change-this-to-a-random-secret-token"
    jwt_secret: str = "change-this-jwt-secret-key"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Admin
    admin_secret: str = ""
    admin_email: str = ""
    app_base_url: str = "http://localhost:3000"

    # Email / SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: bool = True

    # RAG / embeddings
    qdrant_url: str = "http://bob-qdrant:6333"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_batch_size: int = 64
    rag_default_chunk_size: int = 512
    rag_default_chunk_overlap: int = 64
    rag_default_splitter: str = "recursive"
    rag_max_results: int = 20
    rag_staging_path: str = "/data/rag_staging"
    lightrag_storage_path: str = "/data/lightrag"

    class Config:
        env_file = ".env"


settings = Settings()
