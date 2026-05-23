"""Bob Manager — RAG Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.embedding_catalog import get_embedding_dimension, normalize_embedding_model


class RagCollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: str = ""
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int | None = Field(default=None, ge=128, le=4096)
    distance_metric: str = Field(default="cosine", pattern="^(cosine|euclid|dot)$")
    default_chunk_size: int = Field(default=512, ge=64, le=4096)
    default_chunk_overlap: int = Field(default=64, ge=0, le=512)
    default_splitter: str = Field(
        default="recursive",
        pattern="^(recursive|sentence|paragraph|fixed|code)$",
    )
    rag_mode: str = Field(default="vector", pattern="^(vector|lightrag)$")
    lightrag_model_id: UUID | None = None
    lightrag_search_mode: str = Field(default="hybrid", pattern="^(local|global|hybrid)$")

    @field_validator("lightrag_model_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v

    @model_validator(mode="after")
    def validate_embedding_settings(self):
        self.embedding_model = normalize_embedding_model(self.embedding_model)
        expected_dimension = get_embedding_dimension(self.embedding_model)
        if self.embedding_dim is None:
            self.embedding_dim = expected_dimension
            return self
        if self.embedding_dim != expected_dimension:
            raise ValueError(
                f"Embedding dimension for '{self.embedding_model}' must be {expected_dimension}."
            )
        return self


class RagCollectionUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    default_chunk_size: int | None = Field(default=None, ge=64, le=4096)
    default_chunk_overlap: int | None = Field(default=None, ge=0, le=512)
    default_splitter: str | None = Field(
        default=None,
        pattern="^(recursive|sentence|paragraph|fixed|code)$",
    )
    lightrag_model_id: UUID | None = None
    lightrag_search_mode: str | None = Field(
        default=None,
        pattern="^(local|global|hybrid)$",
    )

    @field_validator("lightrag_model_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class RagCollectionResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str
    embedding_model: str
    embedding_dim: int
    distance_metric: str
    default_chunk_size: int
    default_chunk_overlap: int
    default_splitter: str
    document_count: int
    chunk_count: int
    total_size_bytes: int
    rag_mode: str = "vector"
    lightrag_model_id: UUID | None = None
    lightrag_search_mode: str = "hybrid"
    acl: dict = {}
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class RagDocumentResponse(BaseModel):
    id: UUID
    collection_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    chunk_size: int
    chunk_overlap: int
    splitter: str
    chunk_count: int
    status: str
    error_message: str | None = None
    metadata: dict = Field(default_factory=dict)
    ingested_at: datetime | None = None
    created_at: datetime


class RagDocumentReingestRequest(BaseModel):
    chunk_size: int | None = Field(default=None, ge=64, le=4096)
    chunk_overlap: int | None = Field(default=None, ge=0, le=512)
    splitter: str | None = Field(
        default=None,
        pattern="^(recursive|sentence|paragraph|fixed|code)$",
    )

    @model_validator(mode="after")
    def validate_chunk_settings(self):
        if self.chunk_size is not None and self.chunk_overlap is not None and self.chunk_overlap > self.chunk_size:
            raise ValueError("chunk_overlap cannot exceed chunk_size")
        return self


class RagUrlDocumentCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    fetch_mode: str = Field(default="browser", pattern="^(browser|http|auto)$")
    chunk_size: int | None = Field(default=None, ge=64, le=4096)
    chunk_overlap: int | None = Field(default=None, ge=0, le=512)
    splitter: str | None = Field(
        default=None,
        pattern="^(recursive|sentence|paragraph|fixed|code)$",
    )
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_chunk_settings(self):
        if self.chunk_size is not None and self.chunk_overlap is not None and self.chunk_overlap > self.chunk_size:
            raise ValueError("chunk_overlap cannot exceed chunk_size")
        return self


class RagBatchActionResponse(BaseModel):
    queued: int


class RagAccessCreate(BaseModel):
    collection_id: UUID
    can_read: bool = True
    can_write: bool = False


class RagAccessUpdate(BaseModel):
    can_read: bool | None = None
    can_write: bool | None = None


class RagAccessResponse(BaseModel):
    collection_id: UUID
    collection_name: str
    collection_display_name: str
    can_read: bool
    can_write: bool
    created_at: datetime


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    collection: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    score_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    filter: dict = Field(default_factory=dict)
    mode: str | None = Field(default=None, pattern="^(local|global|hybrid)$")


class RagSearchResult(BaseModel):
    document_id: UUID | None = None
    source: str
    text: str
    score: float
    chunk: int
    metadata: dict = Field(default_factory=dict)


class RagSearchResponse(BaseModel):
    collection: str
    results: list[RagSearchResult] = Field(default_factory=list)
