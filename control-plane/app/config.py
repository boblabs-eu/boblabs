"""Bob Manager Control Plane — Configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = (
        "postgresql+asyncpg://bobmanager:changeme_in_production@bob-db:5432/bobmanager"
    )

    # Security
    agent_secret: str = "change-this-to-a-random-secret-token"
    jwt_secret: str = "change-this-jwt-secret-key"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    # Encryption-at-rest key for sensitive DB columns (LLM provider
    # api_keys, MCP auth tokens). Empty = encryption disabled and rows
    # stay plaintext (compat mode). Set to any non-empty string; a
    # 32-byte Fernet key is derived deterministically. After enabling
    # the var, run ``python -m app.scripts.encrypt_secrets`` once to
    # re-encrypt existing plaintext rows in-place.
    key_encryption_secret: str = ""

    # HMAC secret for control-plane <-> sandbox container auth (CSO #8).
    # Closes lateral movement between per-lab sandboxes that share the
    # internal docker network. Empty = unsigned (legacy compat). Must be
    # set to the SAME non-empty value on the sandbox-side env for the
    # sandbox to enforce signatures (container_manager.py passes this
    # secret through to each new sandbox container).
    sandbox_hmac_secret: str = ""

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

    # MCP (Model Context Protocol) client
    mcp_default_timeout_sec: int = 60
    # stdio MCP servers spawn a subprocess on the control-plane host (high
    # trust). Disabled by default; flip to true only for trusted local servers.
    mcp_enable_stdio: bool = False

    # Hermes external agent backend.
    # Docker image for the per-agent Hermes container (real Nous Hermes +
    # the bob hermes-adapter — see hermes-adapter/ADAPTER_CONTRACT.md).
    # Empty = feature degrades gracefully: activation/runs return a clear
    # "Hermes image not configured" error.
    hermes_image: str = ""
    # Hermes turns are slow (its own agent loop + tools, multiplied by the
    # task-completion continuation rounds); matches media_pipeline's 30min.
    hermes_default_timeout_sec: int = 1800
    hermes_internal_port: int = 8770
    # Route Hermes' inference through the internal LLM gateway (LabDispatcher
    # load balancing + concurrency slots + LLM-event feed). False = legacy
    # direct provider calls (no feed visibility, no balancing).
    hermes_use_gateway: bool = True
    # How Hermes containers reach bob-api on the Docker network.
    hermes_gateway_url: str = "http://bob-api:8000"

    class Config:
        env_file = ".env"


settings = Settings()
