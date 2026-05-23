# Changelog

All notable changes to Bob Labs are documented here.

This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.0] — 2026-05-20 — Initial open-source release

This is the first public cut of Bob Labs as
[`boblabs-eu/boblabs`](https://github.com/boblabs-eu/boblabs). The
platform has been running internally with 190+ labs and two consumer
apps; this release exposes the core to anyone who wants to self-host
an agent platform on their own GPUs.

### Added

- Multi-agent **lab runner** with pluggable loop strategies
  (Plan-Execute, Critique-Refine, Round-Robin, solo agent, custom).
- **40 sandboxed built-in tools** across reasoning, memory, file I/O,
  code execution, web, media generation, RAG, database, diagrams,
  comms, data (incl. data.gouv.fr), web3, and ops. See
  [docs/TOOLS_AND_SANDBOX.md](docs/TOOLS_AND_SANDBOX.md).
- **Private RAG** (Qdrant + LightRAG) with per-collection ACLs and
  PDF/Markdown/HTML/URL ingest.
- **GPU dispatcher** across N hosts — auto-discovery of agents,
  least-loaded routing, retry on failure, hot-swap on Ollama, live
  load-balancer feed.
- **Sandboxed code/shell execution** per-lab via docker-socket-proxy +
  command allow-list + resource caps.
- **Anti-loop detector** catching semantic repetition and tool-call
  loops, with automatic memory sweep and pause/recovery.
- **Skill files convention** (`templates/skills/<name>.md`) —
  context-file entries on a lab blueprint are materialized to the
  agent's workspace at boot, agents `file_read` them on demand.
- **Consumer-app HMAC channel** (`/api/v1/internal/apps/*`) — admin-
  managed app key registry, per-app RAG/agents/lab namespaces,
  callback delivery, full integration contract documented in
  [docs/CONSUMER_APPS.md](docs/CONSUMER_APPS.md).
- **JWT auth + per-resource ACL** (`owner` / `editors` / `viewers`)
  on labs, projects, resources, RAG collections, wallets, with an
  admin panel for managing access tokens and trial requests.
- **Public `/live` page** with **opt-in visibility per lab** —
  private by default; owners or admins toggle via the Share modal or
  the new Admin → Labs tab.
- **Outreach approval queue** — agents draft cold emails into
  `output/drafts/*.md` with YAML frontmatter; humans approve / edit /
  reject / send via SMTP. No mail ever leaves the platform without a
  human click.
- **9 GPU microservices** (MusicGen, Bark, RVC, CoquiTTS, STT,
  LTX-Video, Wan-Video, Remotion, ComfyUI bridge), each in its own
  compose file, mix-and-match per host.
- **First-class adapters** for Ollama, vLLM, HuggingFace TGI, OpenAI,
  Anthropic, xAI, Groq, DeepSeek.
- **Real-time event bus** — every orchestrator decision, tool call,
  agent message broadcast over WebSocket.
- **Two-command deploy**: `cp .env.example .env && docker compose up
  -d --build`.

### Notes

- Versions of all four components (agent, control-plane, frontend,
  remotion-api) are aligned at **0.9.0**.
- We have not yet committed to SemVer stability for the public API —
  expect minor breaking changes before 1.0.0. Subscribe to the
  release feed to know when they happen.
- All 40 built-in tools pass the smoke gate. See
  [docs/TOOL_TEST_REPORT.md](docs/TOOL_TEST_REPORT.md) for the most
  recent run.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for how to file issues, run
  the dev stack, and submit PRs.
- Security disclosures go to **support@boblabs.eu** — see
  [SECURITY.md](SECURITY.md).

[0.9.0]: https://github.com/boblabs-eu/boblabs/releases/tag/v0.9.0
