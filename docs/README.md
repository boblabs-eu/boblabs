# Bob Labs — Documentation

## Quick Navigation

### Getting Started
| Document | Description |
|----------|-------------|
| [General Overview](GENERAL_OVERVIEW.md) | Product positioning, deployment model, trust boundaries |
| [Quick Launch](QUICK_LAUNCH.md) | Fastest path to a working dev/eval setup |
| [Architecture](ARCHITECTURE.md) | System design, component diagram, protocols, database schema |
| [Installation (Production)](INSTALL_PROD.md) | Step-by-step production deployment with Nginx, SSL, firewall |
| [Configuration](CONFIGURATION.md) | All environment variables across every service |

### Core Platform
| Document | Description |
|----------|-------------|
| [Labs](LABS.md) | Persistent multi-agent lab system — data model, loop strategies, execution engine |
| [Agents Tab](AGENTS_TAB.md) | Agents tab UI — template library, solo agent instances, feed, inspector, file viewer |
| [Agents & Orchestration](AGENTS_AND_ORCHESTRATION.md) | Orchestrator behavior, agent execution model, memory system |
| [Hermes Agent Backend](HERMES.md) | Run the real Nous Hermes agent as an agent backend — container lifecycle, adapter, task-completion protocol |
| [Anti-Loop](ANTI_LOOP.md) | Loop-detection guards for agents and orchestrators |
| [Tools & Sandbox](TOOLS_AND_SANDBOX.md) | All 40 built-in tools, sandbox isolation, safety controls |
| [Prompt Structure](PROMPT_STRUCTURE.md) | Prompt assembly layers for orchestrators and agents |
| [Conversations](CONVERSATIONS.md) | Multi-turn chat with streaming, model routing |
| [Dispatcher & Model Routing](DISPATCHER_AND_MODEL_ROUTING.md) | LLM provider selection, load balancing, concurrency |
| [Scheduling & CRON](SCHEDULING_AND_CRON.md) | Lab scheduling, agent cron injections, deduplication |

### Data & Retrieval
| Document | Description |
|----------|-------------|
| [RAG](RAG.md) | Qdrant-based vector retrieval, access control, ingestion pipeline |
| [LightRAG](LIGHTRAG.md) | Graph-enhanced RAG with LLM entity extraction |

### GPU & Media
| Document | Description |
|----------|-------------|
| [GPU Services](GPU_SERVICES.md) | All 7 GPU microservices — ports, APIs, VRAM, installation |
| [Video Generation](VIDEO_GENERATION.md) | LTX-Video, Wan-Video, Remotion setup and usage |
| [Music Pipelines](MUSIC_PIPELINES.md) | Multi-stage audio generation pipeline architecture |
| [Install LTX-Video](INSTALL_LTX_VIDEO.md) | Dedicated LTX-Video 22B deployment guide |
| [Install Wan-Video](INSTALL_WAN_VIDEO.md) | Dedicated Wan 2.2 deployment guide |

### Infrastructure
| Document | Description |
|----------|-------------|
| [Agent](AGENT.md) | GPU server agent architecture, collectors, inspectors, installation |
| [Projects & Resources](PROJECTS_AND_RESOURCES.md) | Project management, modules, steps, tasks, resources |
| [Web3](WEB3.md) | Wallet tracking, portfolio snapshots, blockchain tools |
| [Trading & DeFi Tools](WEB3_TOOL.md) | On-chain trading, DEX swaps, DeFi data, position tracking |
| [Web3 Labs](WEB3_LABS.md) | Runnable and future-state Web3 lab blueprints, tool gaps, testing notes |
| [Access Control](ACCESS_CONTROL.md) | Token-based auth, admin panel, email notifications |

### Reference
| Document | Description |
|----------|-------------|
| [API Reference](API_REFERENCE.md) | Complete REST & WebSocket endpoint listing |
| [Orchestrator](ORCHESTRATOR.md) | Orchestrator architecture and conversation internals |

### Additional Guides
| Document | Description |
|----------|-------------|
| [YouTube Speech Retrieval](YOUTUBE_SPEECH_RETRIEVAL.md) | YouTube audio extraction and speech-to-text pipeline |

### Consumer Apps (private overlays on top of bob-api)
| Document | Description |
|----------|-------------|
| [Consumer Apps Contract](CONSUMER_APPS.md) | HMAC, headers, endpoints, callbacks — what any private app integrates against |

### Business & Strategy
| Document | Description |
|----------|-------------|
| [Commercialization](COMMERCIALIZATION.md) | Business model, target market, go-to-market strategy |
| [Successful Launch Playbook](SUCCESSFUL_LAUNCH.md) | Week-by-week founder playbook for shipping Bob Labs |
| [Recruitment Use Case](CABINET_RECRUTEMENT.md) | Example: AI-powered recruitment agency (French) |

## Recommended Reading Order

**For operators deploying Bob Labs:**
1. General Overview → 2. Architecture → 3. Installation (Production) → 4. Configuration → 5. Agent → 6. GPU Services

**For developers extending the platform:**
1. Architecture → 2. Labs → 3. Tools & Sandbox → 4. Prompt Structure → 5. API Reference

**For evaluators assessing the product:**
1. General Overview → 2. Labs → 3. Agents & Orchestration → 4. GPU Services

## Audience

- **Operators** deploying Bob Labs on private infrastructure
- **Engineers** extending Labs, agents, tools, or the control plane
- **Evaluators** assessing the platform for enterprise use
- **Contributors** building new features or integrations
