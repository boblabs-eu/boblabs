# Bob Labs — Conversations

## Overview

Conversations are the primary interface for interacting with the orchestrator. Each conversation maintains a multi-turn message history, a model assignment, and ACL-based access control. Messages are streamed back via SSE (Server-Sent Events).

## Concepts

| Concept | Description |
|---------|-------------|
| **Conversation** | A persistent chat session with title, status, model, and message history |
| **Message** | A single user or assistant turn with content, optional images, and metadata |
| **Agent** | An optional AI Agent assigned to the conversation, providing system prompt and tool config |
| **Tools** | Builtin tools that can be enabled per-conversation for tool calling (e.g. web_search, python_exec) |
| **SSE Streaming** | Responses are streamed token-by-token via `text/event-stream` |
| **ACL** | Per-conversation access control (VIEW, EDIT, DELETE) |
| **Context Mode** | Controls how much conversation history is sent to the model |

## Conversation Lifecycle

```
Create → Active (send/receive messages) → Archive or Delete
```

Each conversation tracks:
- **title** — Display name (auto-generated or user-set)
- **status** — Filter conversations by state
- **model** — LLM model assignment (optional override per message)
- **agent_id** — Optional FK to an AI Agent from the Agents tab. When set, the agent's system prompt, model, and temperature are used.
- **tools** — Optional list of builtin tool names enabled for this conversation (e.g. `["web_search", "python_exec"]`). Enables tool calling in chat.
- **created_at / updated_at** — Timestamps
- **last_message** — Preview of the most recent message
- **message_count** — Total messages in the conversation
- **acl** — Access control list for the owning user

## API Endpoints

All under `/api/v1/orchestrator/conversations`. All endpoints require authentication.

### Conversations

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/conversations` | — | List user's conversations (query: `conv_status`) |
| POST | `/conversations` | — | Create a new conversation |
| GET | `/conversations/{conv_id}` | VIEW | Get conversation details |
| PUT | `/conversations/{conv_id}` | EDIT | Update title, status, or model |
| DELETE | `/conversations/{conv_id}` | DELETE | Delete conversation and all messages |

### Messages

| Method | Path | Permission | Description |
|--------|------|------------|-------------|
| GET | `/conversations/{conv_id}/messages` | VIEW | Get message history (query: `limit=200`) |
| POST | `/conversations/{conv_id}/messages` | EDIT | Send a message, receive SSE stream |

## Sending a Message

```bash
curl -N -X POST \
  http://localhost:8888/api/v1/orchestrator/conversations/{conv_id}/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Explain quantum computing",
    "model": "qwen2.5:72b",
    "images": [],
    "context_mode": "full"
  }'
```

### Request Body — `MessageCreate`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | Yes | User message text |
| `model` | string | No | Override the conversation's default model |
| `images` | string[] | No | Base64-encoded image attachments (multimodal) |
| `context_mode` | string | No | How much history to include in context |

### Response — SSE Stream

The response is a `text/event-stream` with the following headers:

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

Tokens are streamed as SSE events. The frontend consumes these to render the response progressively.

## Message Flow

### Simple (No Tools)

```
User sends message
  │
  ▼
POST /conversations/{id}/messages
  │
  ▼
Permission check (EDIT on conversation ACL)
  │
  ▼
OrchestratorService.process_message()
  │
  ├── Load agent config (if agent_id is set)
  ├── Build context from conversation history
  ├── Route to model via Dispatcher
  ├── Stream tokens back as SSE events
  └── Save assistant message to DB
  │
  ▼
Frontend renders streamed response
```

### With Tool Calling

When tools are enabled on a conversation (via the tools panel or inherited from an agent), the LLM can emit tool calls:

```
User sends message
  │
  ▼
LLM receives message + tool definitions
  │
  ▼
LLM responds with tool_call (e.g. web_search, python_exec)
  │
  ▼
ToolExecutor.execute(tool_name, args)
  │
  ▼
Tool result appended to messages
  │
  ▼
LLM re-called with result context
  │
  ▼
Final response streamed to user
```

The tool call loop continues until the LLM produces a final text response (no more tool calls).

## Access Control

Every conversation has an ACL. The system checks permissions before each operation:

| Operation | Required Permission |
|-----------|-------------------|
| View conversation / read messages | `VIEW` |
| Update conversation / send messages | `EDIT` |
| Delete conversation | `DELETE` |

The conversation creator is automatically granted full permissions.

See [ACCESS_CONTROL.md](ACCESS_CONTROL.md) for the full ACL system.

## Related Documents

- [ORCHESTRATOR.md](ORCHESTRATOR.md) — Orchestrator architecture and model routing
- [DISPATCHER_AND_MODEL_ROUTING.md](DISPATCHER_AND_MODEL_ROUTING.md) — How models are selected and requests dispatched
- [ACCESS_CONTROL.md](ACCESS_CONTROL.md) — Permission system
