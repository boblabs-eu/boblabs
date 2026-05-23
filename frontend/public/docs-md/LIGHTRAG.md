# LightRAG — Graph-Enhanced RAG

Reference documentation for the LightRAG integration in Bob Manager.

---

## Overview

Bob Manager supports two RAG modes per collection:

| | **Vector** (default) | **LightRAG** |
|---|---|---|
| Ingestion | Chunk → embed → Qdrant | Chunk → LLM entity extraction → knowledge graph + embeddings |
| Search | Vector similarity | `local` / `global` / `hybrid` (graph + vector) |
| LLM required for ingestion | No | Yes (entity/relationship extraction) |
| Chunking config | User-controlled (size, overlap, splitter) | Handled internally by LightRAG |
| Best for | Simple lookups, small doc sets | Interconnected content, multi-hop reasoning, entity queries |

Both modes coexist. The mode is chosen at collection creation time and cannot be changed afterward.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  bob-api                                                 │
│                                                          │
│  RagService (rag_service.py)                             │
│    ├─ vector collections → EmbeddingService → Qdrant     │
│    └─ lightrag collections → LightRagService             │
│                                    │                     │
│         ┌──────────────────────────┘                     │
│         │                                                │
│  LightRagService (lightrag_service.py)                   │
│    ├─ LLM calls → LabDispatcher._call_with_loadbalance   │
│    ├─ Embeddings → EmbeddingService (shared)             │
│    └─ Graph storage → /data/lightrag/{collection_id}/    │
│                         ├─ graph_chunk_entity_relation.graphml │
│                         ├─ kv_store_*                    │
│                         └─ vdb_*                         │
└──────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **LLM calls route through `LabDispatcher`**, not direct HTTP. This gives load balancing, provider affinity, retries, and visibility in the LLM Activity dashboard.
- **One LLM per collection.** LightRAG builds a knowledge graph with entities and relationships extracted by a single model. Mixing models mid-collection would produce inconsistent entity names and relationships. The LLM is set at creation and shown (read-only) in collection settings.
- **File-based graph storage** with no Neo4j dependency. Each collection gets its own directory under `/data/lightrag/`.
- **Embeddings are shared** — the same `EmbeddingService` (sentence-transformers running locally) is used for both vector and LightRAG collections.

---

## Data Model

### Database Columns (migration `018_lightrag.sql`)

```sql
ALTER TABLE rag_collections
  ADD COLUMN rag_mode VARCHAR(20) NOT NULL DEFAULT 'vector'
    CHECK (rag_mode IN ('vector', 'lightrag'));

ALTER TABLE rag_collections
  ADD COLUMN lightrag_model_id UUID REFERENCES ai_models(id) ON DELETE SET NULL;

ALTER TABLE rag_collections
  ADD COLUMN lightrag_search_mode VARCHAR(10) NOT NULL DEFAULT 'hybrid'
    CHECK (lightrag_search_mode IN ('local', 'global', 'hybrid'));
```

### ORM (`models/rag.py`)

```python
rag_mode: Mapped[str]           # "vector" or "lightrag"
lightrag_model_id: Mapped[UUID] # FK to ai_models — the LLM used for entity extraction
lightrag_search_mode: Mapped[str] # default search mode: "local", "global", "hybrid"
```

---

## Search Modes

| Mode | What it does | Best for |
|------|-------------|----------|
| `local` | Entity-enriched vector similarity search | Specific factual lookups |
| `global` | Graph traversal across communities | Theme/summary queries across many docs |
| `hybrid` | Both local + global combined | General purpose (recommended default) |

The search mode can be set as a collection default (`lightrag_search_mode`) and overridden per-query via the `mode` parameter in the search API or agent tool.

### Search Output

LightRAG search uses `only_need_context=True` in `QueryParam`, which returns the raw extracted context from the knowledge graph rather than generating an LLM response. This context is then returned as-is to the caller (UI search playground or agent tool).

---

## Ingestion Pipeline

### Vector Collections (unchanged)

```
Document → extract_text() → split_into_chunks(size, overlap, splitter)
         → embed_chunks() → upsert_to_qdrant()
```

### LightRAG Collections

```
Document → extract_text() → LightRAG.ainsert(text)
                              ↓ internally:
                              1. Chunk text (LightRAG's own chunking)
                              2. For each chunk → LLM extracts entities + relationships
                              3. Build/update knowledge graph
                              4. Embed chunks into internal vector store
                              5. Persist graph + KV stores to disk
```

LightRAG handles its own chunking and embedding internally. The chunk size, chunk overlap, and splitter settings in the collection are **ignored** for LightRAG collections — they only apply to vector mode. The UI hides these fields for LightRAG collections.

---

## API

### Create Collection

```
POST /api/v1/rag/collections
{
  "name": "research_papers",
  "display_name": "ML Research Papers",
  "rag_mode": "lightrag",
  "lightrag_model_id": "<uuid-of-ai-model>",
  "lightrag_search_mode": "hybrid",
  "embedding_model": "all-MiniLM-L6-v2",
  "embedding_dim": 384
}
```

- `rag_mode` — `"vector"` (default) or `"lightrag"`.
- `lightrag_model_id` — Required for LightRAG. UUID of an AI model from the models registry. This model is used for entity/relationship extraction during ingestion.
- `lightrag_search_mode` — Default search mode for queries. `"hybrid"` (default), `"local"`, or `"global"`.

### Update Collection

```
PUT /api/v1/rag/collections/{id}
{
  "display_name": "Updated Name",
  "description": "Updated description"
}
```

For vector collections, `default_chunk_size`, `default_chunk_overlap`, and `default_splitter` can also be updated. For LightRAG collections, `lightrag_model_id` and `lightrag_search_mode` can be updated (though changing the model after documents are ingested is not recommended).

### Search

```
POST /api/v1/rag/collections/{id}/search
{
  "query": "How does X relate to Y?",
  "mode": "hybrid"
}
```

The `mode` parameter overrides the collection default for LightRAG collections. For vector collections, it is ignored.

### Document Upload / URL Ingest

Same endpoints for both modes. For LightRAG collections, the chunk_size/overlap/splitter parameters in the upload are ignored — LightRAG handles chunking internally.

---

## Agent Tools

### `rag_list_collections`

Lists all RAG collections accessible to the lab. Output includes `rag_mode` so agents know which collections support graph queries.

### `rag_search`

```json
{
  "query": "string (required)",
  "collection": "string (required) — collection name",
  "top_k": "integer — number of results (vector mode only)",
  "mode": "string — local/global/hybrid (LightRAG only)",
  "filter": "object — metadata filter (vector mode only)",
  "score_threshold": "number — minimum similarity (vector mode only)"
}
```

For LightRAG collections, the `mode` parameter controls the search strategy. The `top_k`, `filter`, and `score_threshold` parameters only apply to vector collections.

---

## LightRagService Implementation

Located at `control-plane/app/services/lightrag_service.py`.

### Instance Management

- **Singleton cache**: `_instances: dict[str, LightRAG]` maps `collection_id` → `LightRAG` instance.
- **Lazy init**: `_get_or_create()` builds an instance on first use, calls `initialize_storages()` + `initialize_pipeline_status()`, and caches it.
- **Storage path**: `/data/lightrag/{collection_id}/` (Docker volume: `lightrag_data`).

### LLM Integration

```python
def _make_dispatcher_llm_func(model_identifier: str):
    async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        async with async_session() as db:
            dispatcher = LabDispatcher(db)
            result = await dispatcher._call_with_loadbalance(
                model_identifier=model_identifier,
                messages=messages,
                temperature=0.0,
                max_tokens=4096,
                caller_name="LightRAG",
                caller_type="lightrag",
            )
        return result["content"]
    return llm_func
```

This closure is passed to `LightRAG(llm_model_func=...)`. Every entity extraction call during ingestion flows through the dispatcher's load balancer.

### Embedding Integration

Uses the shared `EmbeddingService` via a bridge function:

```python
async def _bob_embedding_func(texts: list[str]) -> np.ndarray:
    vectors = await EmbeddingService.embed_texts(texts)
    return np.array(vectors, dtype=np.float32)
```

---

## Frontend Behavior

### Collection Creation

The create form shows a RAG Mode toggle. When "LightRAG" is selected:
- An LLM Model dropdown appears (populated from the AI models registry)
- A Search Mode selector appears (local / global / hybrid)
- Chunk size, overlap, and splitter fields are hidden

### Collection Settings

For LightRAG collections:
- Shows LLM model and search mode as read-only information
- Hides chunk size, overlap, and splitter controls
- Shows document count and total size (no chunk count)

For vector collections:
- Shows chunk size, overlap, and splitter as editable fields
- Shows document count, chunk count, and total size

### Document List

For LightRAG collections:
- Hides the "Chunks" and "Config" columns
- Hides per-document chunk/splitter override controls
- Shows an info note that LightRAG handles chunking internally

### Upload / Ingest

For LightRAG collections:
- Hides the chunk size, overlap, and splitter config fields in both file upload and URL ingest forms

### Search Playground

For LightRAG results:
- Shows the search mode badge instead of score/chunk info
- Does not display raw metadata JSON

---

## Docker Configuration

```yaml
# docker-compose.yml
services:
  bob-api:
    volumes:
      - lightrag_data:/data/lightrag

volumes:
  lightrag_data:
```

The `lightrag_data` volume persists the knowledge graphs across container restarts.

---

## Dependencies

- `lightrag-hku` (PyPI) — the LightRAG library
- No Neo4j or external graph database required
- Uses file-based NetworkX storage by default

---

## Limitations

1. **One LLM per collection** — Cannot use different LLMs for different documents within the same LightRAG collection. The entity extraction model is set at collection creation.
2. **No incremental graph updates on re-ingest** — Re-ingesting a document adds to the graph; it does not remove previously extracted entities from the old version.
3. **Ingestion speed** — LightRAG ingestion is slower than vector-only because each chunk requires an LLM call for entity extraction.
4. **Search results** — LightRAG returns a single context block rather than individual ranked chunks. Score and chunk number are not meaningful for LightRAG results.
