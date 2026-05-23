# Bob Labs — General Overview

## Product Definition

Bob Labs is a self-hosted AI operations platform for running persistent multi-agent workspaces on private infrastructure. It combines:

- a React-based operator interface
- a FastAPI control plane
- a model-aware dispatcher for orchestrator and agent calls
- per-Lab sandbox containers for code and shell execution
- optional private RAG via Qdrant
- supporting monitoring, persistence, and event streaming layers

The platform is designed for teams that need strong control over data location, model routing, workflow behavior, and integration boundaries.

## Commercial Positioning

Bob Labs should be positioned as:

**Private AI Labs on your infrastructure**

This framing is stronger than pure "GPU server management" because the implemented platform already covers the higher-value workflow layer:

- orchestrated multi-agent execution
- persistent Labs with pause and resume
- private retrieval over internal data
- sandboxed tool execution
- enterprise-friendly deployment boundaries

## Deployment Model

The default deployment model is self-hosted.

Typical runtime components:

- `bob-ui` for the frontend
- `bob-api` for the control plane
- `bob-db` for PostgreSQL
- `bob-qdrant` for vector retrieval when RAG is enabled
- one or more GPU-backed model providers such as Ollama or vLLM
- host-level agents on GPU servers for hardware monitoring and command execution

## Core Trust Boundaries

The product is built around explicit isolation boundaries:

- The control plane owns orchestration, persistence, access checks, and websocket broadcasting.
- Per-Lab sandbox containers execute bounded code and shell tools separately from the control plane process.
- RAG access is enforced by the control plane. Sandboxes do not directly access Qdrant.
- GPU model providers are treated as execution backends and are routed through the dispatcher layer.
- Uploaded resources and output files are scoped to each Lab workspace.

## Major Subsystems

### 1. Frontend

The React frontend provides:

- the operational dashboard
- orchestration and Labs views
- RAG management
- resource and output browsing
- live activity via websocket events

### 2. Control Plane

The FastAPI control plane provides:

- REST APIs
- websocket event distribution
- orchestration and Lab lifecycle management
- repository and service layers
- RAG ingestion and query brokering
- scheduler processes
- sandbox lifecycle management

### 3. Labs Runtime

The Labs runtime is the main product differentiator. It supports:

- persistent Lab records
- orchestrator and agent definitions
- pluggable loop strategies
- tool execution loops
- message history
- memory persistence
- resource handling
- pause, resume, stop, reset, duplicate, export, and import flows

### 4. Model Routing

LLM calls are not sent blindly to a single endpoint. The dispatcher layer:

- discovers candidate providers for a requested model
- tracks queue depth and concurrency
- routes to the least-loaded compatible provider
- retries on failure across alternative providers
- logs request lifecycle events

### 5. Tools And Sandboxes

Agents can execute a bounded set of tools. For code and shell execution, each Lab gets an isolated container with its own resource and output scope. This keeps the control plane outside the execution environment and makes per-Lab cleanup practical.

### 6. Private RAG

RAG is implemented as an optional sidecar architecture using Qdrant with explicit Lab-to-collection access entries stored in PostgreSQL. Collections are inaccessible until linked to a Lab.

## Current Implementation Shape

Based on the repository documentation, the platform already includes:

- server and GPU monitoring
- remote commands and workflow execution
- conversation-centric orchestration
- persistent multi-agent Labs
- tool execution and sandbox management
- private RAG foundations plus UI
- websocket-based live activity streams
- scheduling for Labs and agent injections

The current product therefore supports both infrastructure management and private AI workflow orchestration inside the same operational surface.

## Enterprise Evaluation Notes

For enterprise buyers, the strongest current value lies in:

- data locality
- open-source inspectability
- self-hosted deployment
- customization of prompts, tools, models, and workflows
- explicit operational boundaries

For enterprise expansion, the roadmap already points toward:

- multi-user support
- RBAC
- auditability and governance features
- broader deployment hardening

## Related Documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture reference
- [LABS.md](LABS.md) — Labs runtime deep dive
- [AGENTS_AND_ORCHESTRATION.md](AGENTS_AND_ORCHESTRATION.md) — Multi-agent orchestration
- [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md) — Tool reference and sandbox model
- [SCHEDULING_AND_CRON.md](SCHEDULING_AND_CRON.md) — Cron scheduling for labs and agents
- [DISPATCHER_AND_MODEL_ROUTING.md](DISPATCHER_AND_MODEL_ROUTING.md) — LLM routing and load balancing
- [RAG.md](RAG.md) — Vector RAG architecture
- [LIGHTRAG.md](LIGHTRAG.md) — Graph-enhanced RAG
- [ORCHESTRATOR.md](ORCHESTRATOR.md) — Orchestrator settings, providers, conversations
- [ACCESS_CONTROL.md](ACCESS_CONTROL.md) — Authentication and authorization
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variable reference
- [GPU_SERVICES.md](GPU_SERVICES.md) — GPU pipeline services
- [INSTALL_PROD.md](INSTALL_PROD.md) — Production deployment guide
