# Bob Labs — RAG & Vector DB Architecture

> Reference document for the RAG module in Bob Labs.
> Covers architecture, implementation, security model, and integration with Labs.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals & Constraints](#2-goals--constraints)
3. [Architecture Decision: Qdrant Sidecar](#3-architecture-decision-qdrant-sidecar)
4. [Data Model](#4-data-model)
5. [Security: Collection-Level Access Control](#5-security-collection-level-access-control)
6. [Ingestion Pipeline](#6-ingestion-pipeline)
7. [RAG Query Flow](#7-rag-query-flow)
8. [Sandbox & Container Changes](#8-sandbox--container-changes)
9. [New Tools for Agents](#9-new-tools-for-agents)
10. [API Endpoints](#10-api-endpoints)
11. [Frontend UI](#11-frontend-ui)
12. [Docker Compose Changes](#12-docker-compose-changes)
13. [File Structure](#13-file-structure)
14. [Implementation Plan](#14-implementation-plan)
15. [Configuration Reference](#15-configuration-reference)
16. [Migration from Current Memory Search](#16-migration-from-current-memory-search)

---

## 1. Overview

RAG (Retrieval-Augmented Generation) allows labs to query large document collections via semantic search. Instead of relying on keyword-matching (`ILIKE`) over small in-memory stores, agents can search across structured knowledge bases using vector similarity.

The RAG module is a **pluggable sidecar** — labs opt-in to specific collections. No lab has access to any collection unless explicitly granted.

### Current State (Before)

```
Agent → memory_search(query) → ILIKE keyword match over LabMemory rows (max ~50)
                                 ↓
                          Simple substring match — no semantic understanding
```

### Target State (After)

```
Agent → rag_search(query, collection) → Embedding → Qdrant vector similarity
                                          ↓
                              Top-K semantically similar chunks with metadata
                              + existing memory_search still works (unchanged)
```

---

## 2. Goals & Constraints

### Must Have

| # | Requirement |
|---|-------------|
| G1 | **Collection isolation** — Labs access ONLY explicitly allowed collections |
| G2 | **Self-hosted** — No external API calls for embeddings or vector search |
| G3 | **Configurable ingestion** — User controls chunk size, overlap, splitting strategy |
| G4 | **Modular** — RAG is a pluggable module, not baked into core lab logic |
| G5 | **Multiple collections** — User can create themed collections (personal, engineering, docs, etc.) |
| G6 | **Secure by default** — A new collection is accessible to zero labs until explicitly linked |

### Nice to Have

| # | Requirement |
|---|-------------|
| N1 | Cross-lab collection sharing (same collection used by multiple labs) |
| N2 | Auto-ingest lab output files into a collection |
| N3 | Collection versioning / snapshots |
| N4 | Hybrid search (vector + keyword BM25) |

### Non-Goals

- Cloud-hosted vector DB (Pinecone, Weaviate Cloud, etc.)
- Real-time streaming ingestion
- Multi-tenant authentication (single-user system)

---

## 3. Architecture Decision: Qdrant Sidecar

### Why Qdrant

| Criteria | Qdrant | pgvector | ChromaDB | FAISS |
|----------|--------|----------|----------|-------|
| **Collection isolation** | Native collections with independent configs | Schema-level only | Collections supported | Manual index separation |
| **API** | REST + gRPC, battle-tested | SQL queries | Python-only client | In-process only |
| **Persistence** | Built-in WAL + snapshots | PostgreSQL storage | SQLite backend | Manual save/load |
| **Filtering** | Rich payload filters (metadata) | WHERE clauses | Limited | None |
| **Scalability** | Scales to millions of vectors | Limited by PG memory | Small-scale only | Read-only after build |
| **Docker-ready** | Official image, 50MB RAM idle | Already running (PG) | Needs separate service | Library, not service |
| **Maintenance** | Zero-config, self-contained | Shares DB load | Fragile at scale | Manual |

**Decision: Qdrant** — Best collection isolation, rich filtering, production-grade, low resource footprint. Runs as a Docker sidecar alongside bob-db.

**Why not pgvector?** While simpler (reuses existing PostgreSQL), it shares database load with the main application, has weaker collection isolation (just different tables), and lacks Qdrant's metadata filtering capabilities. Keeping vector search separate also means a vector DB issue never impacts the main application database.

### Embedding Model

**Model: `all-MiniLM-L6-v2`** via `sentence-transformers`

- 384-dimensional embeddings
- ~80MB model size, loads in <2s
- Runs on CPU (no GPU required)
- MIT license, fully self-hosted
- Good balance of quality vs speed for RAG use cases

The embedding model runs **inside bob-api** (control plane) — not in the sandbox. Agents never interact with embeddings directly; they call `rag_search` which handles embedding + query internally.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Bob Manager                              │
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌────────────────────┐    │
│  │ Frontend  │───▶│   bob-api     │───▶│     bob-qdrant     │    │
│  │ (bob-ui)  │    │              │    │   (Qdrant v1.12+)  │    │
│  └──────────┘    │  Services:   │    │                    │    │
│                  │  ┌──────────┐│    │  Collections:      │    │
│                  │  │ RAG      ││◀──▶│  ├─ personal_prefs │    │
│                  │  │ Manager  ││    │  ├─ eng_knowledge  │    │
│                  │  └──────────┘│    │  ├─ project_docs   │    │
│                  │  ┌──────────┐│    │  └─ crypto_research│    │
│                  │  │ Embedding││    │                    │    │
│                  │  │ Service  ││    │  Volume:           │    │
│                  │  └──────────┘│    │  qdrant_data       │    │
│                  └──────────────┘    └────────────────────┘    │
│                         │                                      │
│                         ▼                                      │
│                  ┌──────────────┐                               │
│                  │   bob-db      │    Access control stored in  │
│                  │ (PostgreSQL)  │◀── rag_collections +         │
│                  │              │    lab_rag_access tables      │
│                  └──────────────┘                               │
│                                                                 │
│  Per-Lab Sandbox (bob-lab-xxx):                                │
│  ┌──────────────────────────────┐                               │
│  │ NO direct Qdrant access      │  Agents call rag_search tool │
│  │ Tools proxy through bob-api  │  which goes through access   │
│  │                              │  control in the control plane │
│  └──────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

**Critical security point:** Sandbox containers have NO network access to Qdrant. The `rag_search` tool executes inside bob-api (control plane), which checks collection access before querying Qdrant.

---

## 4. Data Model

### PostgreSQL Tables (Access Control & Metadata)

```sql
-- ── RAG Collections ──────────────────────────────
CREATE TABLE IF NOT EXISTS rag_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,         -- "personal_preferences"
    display_name VARCHAR(255) NOT NULL,        -- "Personal Preferences"
    description TEXT DEFAULT '',
    
    -- Embedding config (immutable after first document ingested)
    embedding_model VARCHAR(255) DEFAULT 'all-MiniLM-L6-v2',
    embedding_dim INTEGER DEFAULT 384,
    distance_metric VARCHAR(20) DEFAULT 'cosine',  -- cosine | euclid | dot
    
    -- Ingestion defaults (can be overridden per-document)
    default_chunk_size INTEGER DEFAULT 512,         -- tokens
    default_chunk_overlap INTEGER DEFAULT 64,        -- tokens
    default_splitter VARCHAR(50) DEFAULT 'recursive', -- recursive | sentence | paragraph | fixed
    
    -- Stats (updated by ingestion pipeline)
    document_count INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ── RAG Documents (source tracking) ─────────────
CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES rag_collections(id) ON DELETE CASCADE,
    
    filename VARCHAR(500) NOT NULL,             -- original filename
    content_type VARCHAR(255) DEFAULT 'text/plain',
    size_bytes BIGINT DEFAULT 0,
    
    -- Ingestion config used for this document
    chunk_size INTEGER NOT NULL,
    chunk_overlap INTEGER NOT NULL,
    splitter VARCHAR(50) NOT NULL,
    chunk_count INTEGER DEFAULT 0,
    
    -- Status: pending | processing | ready | failed
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    
    -- Metadata stored as payload filter in Qdrant chunks
    metadata JSONB DEFAULT '{}',               -- arbitrary user tags
    
    ingested_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ── Lab ↔ Collection Access (the security gate) ─
CREATE TABLE IF NOT EXISTS lab_rag_access (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lab_id UUID NOT NULL REFERENCES labs(id) ON DELETE CASCADE,
    collection_id UUID NOT NULL REFERENCES rag_collections(id) ON DELETE CASCADE,
    
    -- Permissions
    can_read BOOLEAN DEFAULT TRUE,              -- query the collection
    can_write BOOLEAN DEFAULT FALSE,            -- ingest new documents (future)
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(lab_id, collection_id)
);
```

### Qdrant Collections

Each `rag_collection` maps 1:1 to a Qdrant collection with the same name.

```python
# Qdrant collection created with:
qdrant_client.create_collection(
    collection_name="personal_preferences",
    vectors_config=VectorParams(
        size=384,            # embedding_dim
        distance=Distance.COSINE,
    ),
)
```

### Qdrant Point (Chunk) Schema

Each chunk stored in Qdrant has:

```json
{
    "id": "uuid",
    "vector": [0.023, -0.187, ...],   // 384-dim embedding
    "payload": {
        "document_id": "uuid",         // FK to rag_documents
        "collection_id": "uuid",       // FK to rag_collections  
        "text": "The actual chunk text content...",
        "chunk_index": 3,              // position within document
        "filename": "architecture.md",
        "metadata": {                  // user-defined tags
            "category": "engineering",
            "source": "internal-wiki"
        }
    }
}
```

---

## 5. Security: Collection-Level Access Control

### Access Control Flow

```
Agent calls rag_search("how to deploy", collection="eng_knowledge")
         │
         ▼
┌─ ToolExecutor (bob-api) ─────────────────────────────┐
│                                                       │
│  1. Resolve collection name → rag_collections.id      │
│  2. CHECK: lab_rag_access WHERE lab_id = X            │
│     AND collection_id = Y AND can_read = TRUE         │
│  3. If NO row → DENY with clear error message         │
│  4. If allowed → embed query → search Qdrant          │
│  5. Return top-K chunks                               │
└───────────────────────────────────────────────────────┘
```

### Security Rules

| Rule | Enforcement |
|------|-------------|
| **Default deny** | No `lab_rag_access` row = no access |
| **No wildcard access** | Each collection must be explicitly linked per-lab |
| **Read/write separation** | `can_read` and `can_write` are independent flags |
| **No direct DB access** | Sandbox containers cannot reach Qdrant (no network route) |
| **Tool-level gating** | `rag_search` tool only available when lab has ≥1 linked collection |
| **Collection list visibility** | `rag_list_collections` only returns collections the lab can access |
| **Audit trail** | Every query logged with lab_id, collection, query text, result count |

### Network Isolation

```yaml
# docker-compose.yml
services:
  bob-qdrant:
    networks:
      - rag-internal     # Only bob-api can reach Qdrant
    # NOT on bob-network — sandbox containers cannot reach it

  bob-api:
    networks:
      - bob-network       # Sandbox + frontend access
      - rag-internal      # Qdrant access
```

Sandbox containers are on `bob-network` only. Qdrant is on `rag-internal` only. **bob-api bridges both networks** and is the sole gateway.

---

## 6. Ingestion Pipeline

### Overview

```
User uploads file(s) via UI
         │
         ▼
┌─ bob-api ────────────────────────────────────────────┐
│                                                       │
│  1. Store file in /data/rag_staging/{collection_id}/  │
│  2. Create rag_documents row (status: pending)        │
│  3. Queue background ingestion task                   │
│                                                       │
│  ┌─ Ingestion Worker (background task) ────────────┐ │
│  │                                                   │ │
│  │  4. Load file content                             │ │
│  │  5. Parse based on content_type:                  │ │
│  │     - .txt/.md → plain text                       │ │
│  │     - .pdf → PyPDF2 / pdfplumber                  │ │
│  │     - .html → BeautifulSoup strip tags            │ │
│  │     - .csv → row-based chunks                     │ │
│  │     - .json → key-path chunks                     │ │
│  │     - .py/.js/code → function-level splitting     │ │
│  │                                                   │ │
│  │  6. Split into chunks:                            │ │
│  │     - RecursiveCharacterTextSplitter (default)    │ │
│  │     - SentenceSplitter                            │ │
│  │     - ParagraphSplitter                           │ │
│  │     - FixedTokenSplitter                          │ │
│  │                                                   │ │
│  │  7. Generate embeddings (batch, all-MiniLM-L6-v2) │ │
│  │  8. Upsert points to Qdrant collection            │ │
│  │  9. Update rag_documents status → ready           │ │
│  │  10. Update rag_collections stats                 │ │
│  └───────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

### Supported Splitters

| Splitter | Best For | How It Works |
|----------|----------|--------------|
| `recursive` (default) | General text, markdown, docs | Splits on `\n\n` → `\n` → `. ` → ` ` recursively until chunk fits |
| `sentence` | Prose, articles, papers | Splits on sentence boundaries (`.` `!` `?`), respects abbreviations |
| `paragraph` | Well-structured documents | Splits on double newlines, keeps paragraphs intact |
| `fixed` | Uniform chunking | Fixed token-count windows with overlap |
| `code` | Source code files | Splits on function/class boundaries using tree-sitter or regex |

### Configurable Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `chunk_size` | 512 | 64–4096 | Target chunk size in tokens |
| `chunk_overlap` | 64 | 0–512 | Overlap between consecutive chunks (for context continuity) |
| `splitter` | `recursive` | See above | Splitting strategy |
| `metadata` | `{}` | Any JSON | Custom tags attached to every chunk (filterable in queries) |

### Ingestion Service

```python
# control-plane/app/services/rag_service.py

class RagService:
    """Manages RAG collections, ingestion, and queries."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.qdrant = QdrantClient(url=QDRANT_URL)
        self.embedder = None  # Lazy-loaded SentenceTransformer

    def _get_embedder(self):
        if self.embedder is None:
            from sentence_transformers import SentenceTransformer
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self.embedder

    async def ingest_document(
        self,
        collection_id: UUID,
        file_path: Path,
        filename: str,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        splitter: str = "recursive",
        metadata: dict = None,
    ) -> UUID:
        """Parse, chunk, embed, and store a document."""
        ...

    async def search(
        self,
        collection_id: UUID,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.3,
        metadata_filter: dict = None,
    ) -> list[dict]:
        """Embed query and search Qdrant collection."""
        ...

    async def check_access(
        self, lab_id: UUID, collection_name: str, permission: str = "read"
    ) -> UUID | None:
        """Return collection_id if lab has the requested permission, else None."""
        ...
```

---

## 7. RAG Query Flow

### Agent → Result (Step by Step)

```
1. Agent decides to search:
   {"name": "rag_search", "arguments": {"query": "deployment best practices", "collection": "eng_knowledge"}}

2. ToolExecutor._rag_search() in bob-api:
   a. Resolve "eng_knowledge" → collection_id (UUID)
   b. Check lab_rag_access: does this lab have can_read=true?
   c. If denied → return {"success": false, "output": "Access denied to collection 'eng_knowledge'"}
   d. Embed query using all-MiniLM-L6-v2 → 384-dim vector
   e. Search Qdrant:
      qdrant.search(
          collection_name="eng_knowledge",
          query_vector=embedding,
          limit=5,
          score_threshold=0.3,
      )
   f. Format results:
      [
          {"text": "When deploying to production...", "score": 0.87, "source": "deploy-guide.md", "chunk": 3},
          {"text": "Always run health checks...", "score": 0.82, "source": "deploy-guide.md", "chunk": 7},
          ...
      ]

3. Agent receives formatted chunks and incorporates into its response.
```

### Query Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | (required) | Natural language search query |
| `collection` | (required) | Collection name to search |
| `top_k` | 5 | Number of results to return (max 20) |
| `score_threshold` | 0.3 | Minimum similarity score (0–1) |
| `filter` | `{}` | Metadata filter (e.g., `{"category": "deployment"}`) |

---

## 8. Sandbox & Container Changes

### Removing Shell Command Whitelist

Since each lab now runs in its **own isolated container** (Option B), the strict shell whitelist in `sandbox/main.py` is no longer necessary for security. The container IS the sandbox.

**Before:**
```python
SHELL_WHITELIST = {"curl", "wget", "cat", "head", "tail", "wc", "grep", ...}
# Only whitelisted commands allowed
```

**After:**
```python
# No whitelist — container isolation IS the security boundary
SHELL_BLOCKED = {"rm -rf /", "dd if=", "mkfs", ":(){:|:&};:"}  # Only block destructive patterns

@app.post("/shell_exec")
async def shell_exec(req: ShellExecRequest):
    # Allow all commands — agents can mkdir, mv, cp, apt install, etc.
    # Container resource limits (CPU, memory) prevent abuse
    # Container is destroyed on lab reset/delete
    ...
```

### Moving Resources INTO the Container

Currently, resources and outputs live on a shared Docker volume. With per-lab containers, we should give each container its own scoped workspace:

```
Container: bob-lab-{lab_id[:12]}
  /workspace/                     ← cwd for all execution
  /workspace/resources/           ← input files (mounted read-only from host)
  /workspace/output/              ← agent-generated files
  /workspace/project/             ← agent's working directory (mkdir, mv, etc.)
```

**Volume mount changes in container_manager.py:**

```python
volumes = {
    # Lab-specific resource directory — read-only for safety
    f"{LAB_RESOURCES_HOST_PATH}/{lab_id}": {
        "bind": "/workspace/resources",
        "mode": "ro",
    },
    # Lab output directory — read-write
    f"{LAB_RESOURCES_HOST_PATH}/{lab_id}/output": {
        "bind": "/workspace/output",
        "mode": "rw",
    },
    # Ephemeral project workspace — container-local, destroyed on reset
    # (no host mount — lives only inside the container)
}
```

### Container Lifecycle (Updated)

| Event | Container | Workspace |
|-------|-----------|-----------|
| Lab created | Not started | — |
| Lab run (first tool call) | Started, resources mounted | `/workspace/resources/` populated |
| Agent runs `shell_exec("mkdir src && mv data.csv src/")` | Allowed (no whitelist) | `/workspace/project/src/data.csv` |
| Agent runs `shell_exec("apt install -y imagemagick")` | Allowed (within memory limit) | Package installed in container |
| Lab paused | Container stopped (state preserved) | All files preserved |
| Lab resumed | Container restarted | Files still there |
| Lab reset | Container destroyed + recreated | Clean slate |
| Lab deleted | Container destroyed | Volume cleaned up |
| Lab completed | Container stopped | Files preserved for download |

---

## 9. New Tools for Agents

### RAG Tools

```python
BUILTIN_TOOLS["rag_search"] = {
    "description": "Search a vector database collection using semantic similarity. "
                   "Returns the most relevant text chunks matching your query. "
                   "Use rag_list_collections to see available collections first.",
    "parameters": {
        "query": "Natural language search query (be specific and descriptive)",
        "collection": "Name of the collection to search (from rag_list_collections)",
        "top_k": "(optional) Number of results, default 5, max 20",
        "filter": "(optional) JSON metadata filter, e.g. {\"category\": \"deployment\"}",
    },
}

BUILTIN_TOOLS["rag_list_collections"] = {
    "description": "List all RAG collections this lab has access to, with their descriptions and document counts.",
    "parameters": {},
}
```

### Tool Availability Logic

```python
# In ToolExecutor.__init__ or tool resolution:
# rag_search and rag_list_collections are ONLY available
# when the lab has at least one linked collection in lab_rag_access

async def _resolve_available_tools(self, lab_id, requested_tools):
    tools = [...]  # standard resolution
    
    # Only add RAG tools if lab has collection access
    has_rag = await self.db.execute(
        select(LabRagAccess).where(LabRagAccess.lab_id == lab_id).limit(1)
    )
    if has_rag.scalar():
        tools.extend(["rag_search", "rag_list_collections"])
    
    return tools
```

---

## 10. API Endpoints

### Collection Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/collections` | List all collections (admin view) |
| `POST` | `/api/v1/rag/collections` | Create a new collection |
| `GET` | `/api/v1/rag/collections/{id}` | Get collection details + stats |
| `PATCH` | `/api/v1/rag/collections/{id}` | Update display_name, description, defaults |
| `DELETE` | `/api/v1/rag/collections/{id}` | Delete collection + all chunks from Qdrant |

### Document Ingestion

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/collections/{id}/documents` | List documents in collection |
| `POST` | `/api/v1/rag/collections/{id}/documents` | Upload + ingest a document |
| `DELETE` | `/api/v1/rag/collections/{id}/documents/{doc_id}` | Remove document + its chunks |
| `POST` | `/api/v1/rag/collections/{id}/documents/{doc_id}/reingest` | Re-chunk with new settings |

### Lab Access Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/labs/{lab_id}/rag-access` | List collections linked to a lab |
| `POST` | `/api/v1/labs/{lab_id}/rag-access` | Link a collection to a lab |
| `DELETE` | `/api/v1/labs/{lab_id}/rag-access/{collection_id}` | Revoke lab's access to collection |
| `PATCH` | `/api/v1/labs/{lab_id}/rag-access/{collection_id}` | Update permissions (read/write) |

### Search (used internally by tool, also exposed for testing)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/rag/search` | Direct search (admin/debug, bypasses lab access) |

---

## 11. Frontend UI

### Collection Manager (new page or section)

```
┌──────────────────────────────────────────────────────────────────┐
│  RAG Collections                                          + New  │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐              │
│  │ 📚 Personal Prefs   │  │ 🔧 Eng Knowledge    │              │
│  │ 12 documents        │  │ 47 documents         │              │
│  │ 2,341 chunks        │  │ 15,892 chunks        │              │
│  │ 4.2 MB              │  │ 28.7 MB              │              │
│  │                     │  │                      │              │
│  │ Labs: 3 linked      │  │ Labs: 1 linked       │              │
│  │ [Manage] [Delete]   │  │ [Manage] [Delete]    │              │
│  └─────────────────────┘  └─────────────────────┘              │
│                                                                 │
│  Selected: Eng Knowledge                                        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Documents                                        [+ Upload] ││
│  │ ─────────────────────────────────────────────────────────── ││
│  │ ✅ deploy-guide.md      1,234 chunks  |  recursive 512/64  ││
│  │ ✅ api-patterns.pdf     891 chunks    |  sentence  256/32  ││
│  │ ⏳ new-standards.html   processing... |  recursive 512/64  ││
│  │ ❌ corrupt.bin          Failed: unsupported format          ││
│  │                                                             ││
│  │ Default Settings:                                           ││
│  │ Chunk size: [512] tokens   Overlap: [64] tokens             ││
│  │ Splitter:   [recursive ▾]  Distance: [cosine ▾]            ││
│  └─────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

### Lab Config Panel (existing, extended)

In the Lab sidebar config, add a **RAG Collections** section:

```
┌─────────────────────────────────┐
│ 🗂 RAG Collections              │
│ ─────────────────────────────── │
│ ✅ personal_preferences  [×]    │
│ ✅ eng_knowledge         [×]    │
│                                 │
│ [+ Link Collection ▾]          │
│   ☐ crypto_research             │
│   ☐ project_docs                │
└─────────────────────────────────┘
```

### Search Playground (in Collection detail)

A test panel where the user can type queries and see results before linking to a lab:

```
┌─────────────────────────────────────────────┐
│ 🔍 Test Search                              │
│ Query: [how to handle database migrations ] │
│ Top K: [5]  Threshold: [0.30]               │
│                                  [Search]   │
│                                             │
│ Results:                                    │
│ 1. (0.91) deploy-guide.md #42              │
│    "Database migrations should be run..."   │
│ 2. (0.84) api-patterns.pdf #117            │
│    "Always use versioned migrations..."     │
│ 3. (0.73) deploy-guide.md #43              │
│    "Rollback strategy: keep the previous..."│
└─────────────────────────────────────────────┘
```

---

## 12. Docker Compose Changes

```yaml
services:
  # ... existing services ...

  bob-qdrant:
    image: qdrant/qdrant:v1.12.6
    container_name: bob-qdrant
    restart: unless-stopped
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      - QDRANT__SERVICE__HTTP_PORT=6333
      - QDRANT__SERVICE__GRPC_PORT=6334
    networks:
      - rag-internal          # Isolated network — only bob-api can reach
    mem_limit: 1g
    cpus: 1.0
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 3

  bob-api:
    # ... existing config ...
    environment:
      - QDRANT_URL=http://bob-qdrant:6333
      - EMBEDDING_MODEL=all-MiniLM-L6-v2
    networks:
      - bob-network           # Existing: sandbox + frontend
      - rag-internal          # New: Qdrant access
    depends_on:
      bob-db:
        condition: service_healthy
      bob-qdrant:
        condition: service_healthy

networks:
  bob-network:
    driver: bridge
  rag-internal:               # New isolated network
    driver: bridge
    internal: true            # No external access

volumes:
  # ... existing volumes ...
  qdrant_data:                # Persistent vector storage
```

### bob-api Requirements Addition

```
# control-plane/requirements.txt (additions)
qdrant-client>=1.12.0
sentence-transformers>=3.0.0
```

---

## 13. File Structure

```
control-plane/app/
├── models/
│   └── rag.py                    # RagCollection, RagDocument, LabRagAccess models
├── schemas/
│   └── rag.py                    # Pydantic schemas for API I/O
├── repositories/
│   └── rag_repo.py               # RagCollectionRepo, RagDocumentRepo, LabRagAccessRepo
├── services/
│   ├── rag_service.py            # Collection CRUD, search, access control
│   ├── rag_ingest.py             # Ingestion pipeline: parse, chunk, embed, store
│   └── embedding_service.py      # SentenceTransformer wrapper (lazy singleton)
├── api/routes/
│   └── rag.py                    # REST endpoints for collections, documents, access
└── services/
    └── tool_executor.py          # +rag_search, +rag_list_collections tools

sandbox/
└── main.py                       # Remove SHELL_WHITELIST, allow all commands
```

---

## 14. Implementation Plan

### Phase 1: Foundation (Core RAG)

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 1.1 | Add Qdrant to docker-compose + rag-internal network | `docker-compose.yml` | — |
| 1.2 | Create `rag.py` models (RagCollection, RagDocument, LabRagAccess) | `models/rag.py` | — |
| 1.3 | Create `rag.py` schemas | `schemas/rag.py` | 1.2 |
| 1.4 | Create `rag_repo.py` repositories | `repositories/rag_repo.py` | 1.2 |
| 1.5 | Create `embedding_service.py` (lazy SentenceTransformer) | `services/embedding_service.py` | — |
| 1.6 | Create `rag_service.py` (collection CRUD + search) | `services/rag_service.py` | 1.4, 1.5 |
| 1.7 | DB migration: create tables on startup | `main.py` | 1.2 |
| 1.8 | Add `qdrant-client`, `sentence-transformers` to requirements | `requirements.txt` | — |

### Phase 2: Ingestion Pipeline

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 2.1 | Create `rag_ingest.py` (file parsing + chunking) | `services/rag_ingest.py` | 1.6 |
| 2.2 | Implement splitters (recursive, sentence, paragraph, fixed, code) | `services/rag_ingest.py` | 2.1 |
| 2.3 | Background ingestion worker (via BackgroundTasks) | `services/rag_ingest.py` | 2.2 |
| 2.4 | Create RAG API routes (collections + documents + upload) | `api/routes/rag.py` | 1.6, 2.3 |
| 2.5 | Wire routes into `main.py` | `main.py` | 2.4 |

### Phase 3: Lab Integration

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 3.1 | Add `rag_search` and `rag_list_collections` tools | `tool_executor.py` | 1.6 |
| 3.2 | Access control check in tool execution | `tool_executor.py` | 1.6 |
| 3.3 | Lab ↔ Collection linking API endpoints | `api/routes/rag.py` | 1.4 |
| 3.4 | Auto-add RAG tools when lab has linked collections | `tool_executor.py` | 3.1 |

### Phase 4: Sandbox Improvements

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 4.1 | Remove `SHELL_WHITELIST`, allow all commands | `sandbox/main.py` | — |
| 4.2 | Update container_manager workspace mount structure | `container_manager.py` | — |
| 4.3 | Add `apt` and common tools to sandbox Dockerfile | `sandbox/Dockerfile` | — |
| 4.4 | Update `_file_read`/`_file_write` for new workspace layout | `tool_executor.py` | 4.2 |

### Phase 5: Frontend

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 5.1 | RAG Collections page (list, create, delete) | `frontend/src/` | 2.4 |
| 5.2 | Document upload + ingestion status | `frontend/src/` | 2.4 |
| 5.3 | Collection settings (chunk size, splitter, etc.) | `frontend/src/` | 2.4 |
| 5.4 | Lab config: link/unlink collections | `frontend/src/` | 3.3 |
| 5.5 | Search playground | `frontend/src/` | 2.4 |

### Phase 6: Polish

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 6.1 | Ingestion progress WebSocket events | `websocket/hub.py` | 2.3 |
| 6.2 | Re-ingest document with different settings | `api/routes/rag.py` | 2.3 |
| 6.3 | Metadata filters in search UI | `frontend/src/` | 5.5 |
| 6.4 | Query logging / audit trail | `services/rag_service.py` | 3.2 |

---

## 15. Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_URL` | `http://bob-qdrant:6333` | Qdrant HTTP endpoint |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model name |
| `EMBEDDING_BATCH_SIZE` | `64` | Batch size for embedding generation |
| `RAG_DEFAULT_CHUNK_SIZE` | `512` | Default chunk size in tokens |
| `RAG_DEFAULT_CHUNK_OVERLAP` | `64` | Default chunk overlap in tokens |
| `RAG_DEFAULT_SPLITTER` | `recursive` | Default splitting strategy |
| `RAG_MAX_RESULTS` | `20` | Maximum results per query |
| `RAG_STAGING_PATH` | `/data/rag_staging` | Temp storage for uploaded files before ingestion |

### Collection Settings (per-collection, stored in DB)

| Setting | Range | Description |
|---------|-------|-------------|
| `embedding_model` | String | Model used (locked after first ingest) |
| `embedding_dim` | 128–4096 | Dimension count (locked after creation) |
| `distance_metric` | `cosine` / `euclid` / `dot` | Similarity metric |
| `default_chunk_size` | 64–4096 | Target chunk size in tokens |
| `default_chunk_overlap` | 0–512 | Overlap between chunks |
| `default_splitter` | `recursive` / `sentence` / `paragraph` / `fixed` / `code` | Splitting strategy |

### Per-Document Overrides (at upload time)

All collection defaults can be overridden when uploading a specific document:

```json
POST /api/v1/rag/collections/{id}/documents
Content-Type: multipart/form-data

file: deploy-guide.md
chunk_size: 256        // Override for this file only
chunk_overlap: 32
splitter: sentence
metadata: {"category": "ops", "priority": "high"}
```

---

## 16. Migration from Current Memory Search

The existing `memory_search` tool is **not replaced** — it continues to work as-is for lab-scoped keyword search over agent memories. RAG is an **additional** capability.

| Feature | memory_search (existing) | rag_search (new) |
|---------|-------------------------|-------------------|
| Scope | Per-lab agent memories | Cross-lab knowledge collections |
| Search method | Keyword ILIKE substring | Vector cosine similarity |
| Data source | LabMemory rows (runtime) | Pre-ingested document chunks |
| Scale | ~50-100 memories | Millions of chunks |
| Setup | Automatic (agents save) | Manual (user uploads + configures) |
| Access control | Lab-scoped inherently | Explicit collection linking |

### Future Enhancement: Semantic Memory Search

Once RAG infrastructure is in place, `memory_search` can optionally be upgraded to use embeddings too:

```python
# Future: hybrid memory search
async def _memory_search(self, args):
    query = args["query"]
    # Step 1: keyword match (existing)
    keyword_results = [m for m in memories if query.lower() in m.content.lower()]
    # Step 2: semantic match (new, if embeddings available)
    embedding = embed(query)
    semantic_results = cosine_search(memory_embeddings, embedding, top_k=10)
    # Step 3: merge and deduplicate
    return merge(keyword_results, semantic_results)
```

This is a Phase 6+ enhancement — RAG collections come first.


Already Implemented

Infrastructure and runtime wiring are in place.
docker-compose.yml:47 sets Qdrant and embedding environment variables for the API.
docker-compose.yml:92 defines the bob-qdrant service.
docker-compose.yml:102 puts Qdrant on the isolated rag-internal network.
config.py:22 includes the RAG and embedding settings.
requirements.txt:19 includes qdrant-client, sentence-transformers, and pypdf.

The database model and migration layer are implemented.
rag.py:13 defines RagCollection.
rag.py:47 defines RagDocument.
rag.py:82 defines LabRagAccess.
014_rag.sql:1 creates the RAG tables.
main.py:217 bootstraps the RAG schema on startup.

The API routes are implemented and registered.
main.py:54 registers the RAG router.
rag.py:52 creates collections.
rag.py:98 uploads documents for ingestion.
rag.py:185 manages lab-to-collection access.
rag.py:231 exposes direct search.

The repository and service layer are implemented.
rag_repo.py:13 has collection CRUD.
rag_repo.py:58 has document CRUD and stats aggregation.
rag_repo.py:102 has lab access checks.
rag_service.py:92 creates collections and provisions Qdrant collections.
rag_service.py:163 ingests documents.
rag_service.py:382 performs semantic search.
rag_service.py:416 enforces lab access on search.
rag_service.py:445 creates the underlying Qdrant collection if needed.

Embeddings are implemented.
embedding_service.py:12 provides a lazy SentenceTransformer singleton.
embedding_service.py:28 embeds document chunks.
embedding_service.py:45 embeds search queries.

The ingestion pipeline is implemented for the main file types and splitter modes.
rag_ingest.py:59 extracts text from supported files.
rag_ingest.py:64 supports PDF.
rag_ingest.py:75 supports HTML via BeautifulSoup.
rag_ingest.py:79 supports JSON flattening.
rag_ingest.py:85 supports CSV row conversion.
rag_ingest.py:106 supports recursive, sentence, paragraph, fixed, and code splitting.
rag_ingest.py:240 includes a code splitter.

Lab integration is implemented.
tool_executor.py:75 registers rag_list_collections.
tool_executor.py:79 registers rag_search.
tool_executor.py:572 implements rag_list_collections.
tool_executor.py:588 implements rag_search.
rag_service.py:64 auto-adds RAG tools only when the lab has access.
lab_runner.py:220 applies that logic to orchestrator tools.
lab_runner.py:736 applies it to agent tools.
lab_scheduler.py:244 applies it in scheduled runs too.

Partially Implemented

Query audit trail exists only as application logging, not as a durable audit feature.
rag_service.py:436 logs the lab, collection, result count, and query text, but there is no persistent audit table or reporting layer.

The ingestion design is simpler than the doc implies.
rag_ingest.py:106 uses character-based approximations for chunk sizing, not tokenizer-accurate token counts.
rag_ingest.py:240 uses regex-based code splitting, not tree-sitter or AST-aware function/class parsing.

Background ingestion exists, but progress reporting does not.
rag.py:98 schedules ingestion as a background task.
There is no corresponding frontend or websocket progress feature for ingestion status updates.

Still Missing

Frontend support is effectively not implemented.
api.js has exports for labs, tool sets, prompt templates, and other features, but no RAG collection, document, access, or search API wrappers.
A search across frontend source did not find RAG-related components, which means the collection manager, upload UI, lab linking UI, and search playground described in RAG.md:631 and RAG.md:661 are still missing.

The sandbox changes from the doc are not implemented.
main.py:23 still uses a SHELL_WHITELIST.
main.py:132 still blocks commands outside that whitelist.
main.py:21 still uses the lab_resources root layout instead of the proposed workspace layout.
main.py:53 only ensures an output directory, not separate resources, output, and project workspaces.
container_manager.py:64 still mounts a single shared volume at /data/lab_resources rather than the scoped /workspace/resources, /workspace/output, /workspace/project structure from the doc.

The broader sandbox capability upgrades are missing.
Because the whitelist is still present, the doc’s planned behavior of allowing general shell workflows like package installs, mkdir, mv, and broader workspace manipulation is not yet available.

Frontend-driven collection access management is missing.
The backend routes exist in rag.py:185, but there is no visible frontend integration to link and unlink collections from labs.

Search playground and admin collection management UI are missing.
The backend supports the necessary operations, but there is no implemented page or component for testing queries, viewing collection stats, uploading files, or re-ingesting documents.

What I Would Treat As Complete Vs Not Complete

Phase 1 from the doc is complete.
Phase 2 is mostly complete on the backend.
Phase 3 is complete on the backend.
Phase 4 is not complete.
Phase 5 is not complete.
Phase 6 is only partially complete.
Recommended Next Implementation Order

Add frontend API wrappers and UI for collections, documents, lab access, and test search.
Replace the sandbox whitelist model with the per-container workspace model described in the doc.
Add ingestion progress events and a simple UI status surface.
Add durable query audit logging if you need compliance or history beyond plain logs.
Improve chunking accuracy and code-aware splitting only after the UI and sandbox work are done.
If you want, I can turn this into a concrete checklist mapped to files to implement next.