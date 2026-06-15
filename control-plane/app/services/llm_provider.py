"""Bob Manager — LLM Provider abstraction layer.

Supports Ollama, HuggingFace Inference API, OpenAI-compatible APIs
(including the per-server claude-cli wrapper), and Anthropic (Claude) API.
All providers expose a unified interface for chat completion (streaming)
and model discovery.

Message format:
  Standard: [{"role": "user", "content": "text"}]
  Multimodal: [{"role": "user", "content": "text", "images": ["base64..."]}]
  The "images" key is optional. Providers convert it to their native format.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

# Shared HTTP client settings
_TIMEOUT = httpx.Timeout(connect=15.0, read=600.0, write=15.0, pool=30.0)


def _convert_messages_openai(messages: list[dict]) -> list[dict]:
    """Convert internal message format to OpenAI multimodal format.

    If a message has 'images' (list of base64 strings), convert content to
    the multimodal array format [{type: text}, {type: image_url}].
    Handles tool-calling messages (assistant tool_calls + tool results).
    """
    converted = []
    for msg in messages:
        role = msg["role"]

        # Tool result messages
        if role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                }
            )
            continue

        out: dict = {"role": role}
        images = msg.get("images")

        if images:
            content_parts = [{"type": "text", "text": msg.get("content", "")}]
            for img_b64 in images:
                # Try to detect mime type from base64 header or default to png
                if img_b64.startswith("data:"):
                    url = img_b64
                else:
                    url = f"data:image/png;base64,{img_b64}"
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": url},
                    }
                )
            out["content"] = content_parts
        else:
            out["content"] = msg.get("content", "")

        # Assistant messages with native tool_calls
        if role == "assistant" and msg.get("tool_calls"):
            out["tool_calls"] = [
                {
                    "id": tc.get("id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"])
                        if isinstance(tc["arguments"], dict)
                        else tc["arguments"],
                    },
                }
                for i, tc in enumerate(msg["tool_calls"])
            ]

        converted.append(out)
    return converted


def _convert_messages_ollama(messages: list[dict]) -> list[dict]:
    """Convert internal message format to Ollama format.

    Ollama uses 'images' field directly in messages (list of base64 strings without header).
    Handles tool-calling messages (assistant tool_calls + tool results).
    """
    converted = []
    for msg in messages:
        role = msg["role"]

        # Tool result messages
        if role == "tool":
            converted.append({"role": "tool", "content": msg.get("content", "")})
            continue

        out: dict = {"role": role, "content": msg.get("content", "")}

        images = msg.get("images")
        if images:
            # Ollama expects raw base64 without data: prefix
            clean_images = []
            for img_b64 in images:
                if img_b64.startswith("data:"):
                    # Strip data:image/xxx;base64, prefix
                    _, _, b64data = img_b64.partition(",")
                    clean_images.append(b64data)
                else:
                    clean_images.append(img_b64)
            out["images"] = clean_images

        # Assistant messages with native tool_calls
        if role == "assistant" and msg.get("tool_calls"):
            out["tool_calls"] = [
                {"function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in msg["tool_calls"]
            ]

        converted.append(out)
    return converted


def _normalize_ollama_tool_calls(raw: list) -> list[dict]:
    """Normalize Ollama tool_calls response to internal format."""
    calls = []
    for i, tc in enumerate(raw):
        fn = tc.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw_arguments": args}
        calls.append({"id": f"call_{i}", "name": fn.get("name", ""), "arguments": args})
    return calls


def _accumulate_openai_tool_delta(tc_acc: dict, delta: dict) -> None:
    """Accumulate streaming tool-call deltas from OpenAI-format SSE chunks."""
    for tc_delta in delta.get("tool_calls", []):
        idx = tc_delta.get("index", 0)
        if idx not in tc_acc:
            tc_acc[idx] = {
                "id": tc_delta.get("id", f"call_{idx}"),
                "name": "",
                "arguments_str": "",
            }
        fn = tc_delta.get("function", {})
        if fn.get("name"):
            tc_acc[idx]["name"] = fn["name"]
        if fn.get("arguments"):
            tc_acc[idx]["arguments_str"] += fn["arguments"]


def _finalize_openai_tool_calls(tc_acc: dict) -> list[dict]:
    """Convert accumulated SSE tool-call data to internal format."""
    if not tc_acc:
        return []
    calls = []
    for idx in sorted(tc_acc.keys()):
        tc = tc_acc[idx]
        args_str = tc["arguments_str"]
        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            args = {"raw_arguments": args_str}
        calls.append({"id": tc["id"], "name": tc["name"], "arguments": args})
    return calls


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        think: bool | str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream chat completion.

        Yields dicts with:
            {"token": "...", "done": False}
            {"token": "", "done": True, "tokens_in": N, "tokens_out": M, "model": "...",
             "tool_calls": [...] }   # tool_calls only when native tool calling triggered

        `think` is Ollama-only: pass False to skip native chain-of-thought
        on reasoning models (qwen3, etc.), True to force it, or "low"/"medium"/
        "high" for gpt-oss style models. Other providers ignore it.
        """
        yield {}  # pragma: no cover

    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        think: bool | str | None = None,
    ) -> dict:
        """Non-streaming chat: collect all tokens and return a single dict.

        Returns {"content": "...", "tokens_in": N, "tokens_out": M, "model": "...",
                 "tool_calls": [...] }.  tool_calls key present only when model used native calling.
        """
        parts: list[str] = []
        meta: dict = {}
        async for chunk in self.chat_completion(
            messages, model, temperature, max_tokens, tools=tools, think=think
        ):
            if chunk.get("done"):
                meta = chunk
            elif chunk.get("token"):
                parts.append(chunk["token"])
        result = {
            "content": "".join(parts),
            "tokens_in": meta.get("tokens_in", 0),
            "tokens_out": meta.get("tokens_out", 0),
            "model": meta.get("model", model),
        }
        if meta.get("tool_calls"):
            result["tool_calls"] = meta["tool_calls"]
        return result

    @abstractmethod
    async def list_models(self) -> list[dict]:
        """List available models.

        Returns list of dicts: {"name": "...", "identifier": "...", "parameters": {...}}
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable."""


# ── Ollama Provider ───────────────────────────────


class OllamaProvider(LLMProvider):
    """Ollama API provider (local models via ollama serve)."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def chat_completion(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        think: bool | str | None = None,
    ) -> AsyncGenerator[dict, None]:
        payload = {
            "model": model,
            "messages": _convert_messages_ollama(messages),
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["think"] = think
        accumulated_tool_calls: list = []
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data.get("done"):
                        # When tools are provided Ollama may skip streaming
                        # and return the full text in the done message.
                        msg_data = data.get("message", {})
                        final_content = msg_data.get("content", "")
                        final_thinking = msg_data.get("thinking", "")
                        if final_thinking:
                            yield {"token": final_thinking, "done": False}
                        if final_content:
                            yield {"token": final_content, "done": False}
                        done_data = {
                            "token": "",
                            "done": True,
                            "tokens_in": data.get("prompt_eval_count", 0),
                            "tokens_out": data.get("eval_count", 0),
                            "model": data.get("model", model),
                        }
                        # Tool calls may arrive in non-done or done messages
                        raw_tc = (
                            data.get("message", {}).get("tool_calls")
                            or accumulated_tool_calls
                            or None
                        )
                        if raw_tc:
                            done_data["tool_calls"] = _normalize_ollama_tool_calls(raw_tc)
                        yield done_data
                    else:
                        msg = data.get("message", {})
                        content = msg.get("content", "")
                        thinking = msg.get("thinking", "")
                        if thinking:
                            yield {"token": thinking, "done": False}
                        if content:
                            yield {"token": content, "done": False}
                        # Ollama sends tool_calls in non-done chunks
                        if msg.get("tool_calls"):
                            accumulated_tool_calls.extend(msg["tool_calls"])

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            details = m.get("details", {})
            params: dict = {
                "size": m.get("size", 0),
                "parameter_size": details.get("parameter_size", ""),
                "quantization": details.get("quantization_level", ""),
                "family": details.get("family", ""),
                "format": details.get("format", ""),
            }
            # Fetch context_length from /api/show model_info
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as show_client:
                    show_resp = await show_client.post(
                        f"{self.base_url}/api/show", json={"model": name}
                    )
                    if show_resp.status_code == 200:
                        show_data = show_resp.json()
                        model_info = show_data.get("model_info", {})
                        for k, v in model_info.items():
                            if "context_length" in k:
                                params["context_length"] = int(v)
                                break
            except Exception:
                pass  # Non-critical — context_length is informational only
            models.append({"name": name, "identifier": name, "parameters": params})
        return models

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False


# ── HuggingFace Inference Provider ────────────────


class HuggingFaceProvider(LLMProvider):
    """HuggingFace Inference API provider."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._max_model_len: dict[str, int] = {}  # model -> max ctx len

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _get_max_model_len(self, model: str) -> int | None:
        """Query /v1/models to get max_model_len for a model. Cached."""
        if model in self._max_model_len:
            return self._max_model_len[model]
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/v1/models", headers=self._headers())
                resp.raise_for_status()
                for m in resp.json().get("data", []):
                    if m.get("id") == model:
                        ml = m.get("max_model_len")
                        if ml:
                            self._max_model_len[model] = int(ml)
                            return int(ml)
        except Exception:
            pass
        return None

    def _cap_max_tokens(self, max_tokens: int, max_model_len: int | None) -> int:
        """Cap max_tokens to the model's context window (when known).

        The user can now set max_tokens freely per agent/orchestrator.
        We only hard-cap to max_model_len to avoid definite API errors.
        """
        if max_model_len is None:
            return max_tokens
        return min(max_tokens, max_model_len)

    async def chat_completion(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        think: bool | str | None = None,  # Ollama-only; silently ignored here
    ) -> AsyncGenerator[dict, None]:
        model_len = await self._get_max_model_len(model)
        capped_max_tokens = self._cap_max_tokens(max_tokens, model_len)

        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": _convert_messages_openai(messages),
            "max_tokens": capped_max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        total_tokens_in = 0
        total_tokens_out = 0
        tc_acc: dict = {}  # tool-call accumulator for streaming deltas

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # If tools are included and the provider rejects them (e.g. vLLM
            # without --enable-auto-tool-choice), retry without tools.
            for _attempt in range(2):
                async with client.stream(
                    "POST", url, json=payload, headers=self._headers()
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        error_text = body.decode(errors="replace")[:2000]
                        logger.error(
                            "HuggingFace/vLLM error %s: %s", response.status_code, error_text
                        )
                        if "tools" in payload and "tool" in error_text.lower():
                            logger.warning(
                                "Provider does not support native tool calling; retrying without tools"
                            )
                            payload.pop("tools", None)
                            continue  # retry without tools
                        response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw == "[DONE]":
                            done_data = {
                                "token": "",
                                "done": True,
                                "tokens_in": total_tokens_in,
                                "tokens_out": total_tokens_out,
                                "model": model,
                            }
                            tool_calls = _finalize_openai_tool_calls(tc_acc)
                            if tool_calls:
                                done_data["tool_calls"] = tool_calls
                            yield done_data
                            return
                        data = json.loads(raw)
                        usage = data.get("usage")
                        if usage:
                            total_tokens_in = usage.get("prompt_tokens", 0)
                            total_tokens_out = usage.get("completion_tokens", 0)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        _accumulate_openai_tool_delta(tc_acc, delta)
                        content = delta.get("content", "")
                        if content:
                            yield {"token": content, "done": False}
                # Streamed successfully — exit retry loop
                break

        done_data = {
            "token": "",
            "done": True,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "model": model,
        }
        tool_calls = _finalize_openai_tool_calls(tc_acc)
        if tool_calls:
            done_data["tool_calls"] = tool_calls
        yield done_data

    async def list_models(self) -> list[dict]:
        # Try OpenAI-compatible /v1/models (works for vLLM, TGI, etc.)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
            return [
                {
                    "name": m.get("id", ""),
                    "identifier": m.get("id", ""),
                    "parameters": {},
                }
                for m in data.get("data", [])
            ]
        except Exception as e:
            logger.warning("HuggingFace list_models via /v1/models failed: %s", e)
            return []

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False


# ── OpenAI-Compatible Provider ────────────────────


class OpenAICompatibleProvider(LLMProvider):
    """Any OpenAI-compatible API (OpenAI, vLLM, LocalAI, LM Studio, etc.)."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def chat_completion(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        think: bool | str | None = None,  # Ollama-only; silently ignored here
    ) -> AsyncGenerator[dict, None]:
        payload = {
            "model": model,
            "messages": _convert_messages_openai(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
        total_tokens_in = 0
        total_tokens_out = 0
        tc_acc: dict = {}  # tool-call accumulator for streaming deltas

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code >= 400:
                    # Surface the upstream error BODY (e.g. the Claude CLI
                    # wrapper's {"detail": "claude CLI error: <real reason>"}),
                    # not just the bare status line — so a paused/failed lab
                    # shows WHY (rate limit vs overload vs context).
                    body = (await response.aread()).decode(errors="replace")[:600]
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code} from {self.base_url}: {body}",
                        request=response.request,
                        response=response,
                    )
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        done_data = {
                            "token": "",
                            "done": True,
                            "tokens_in": total_tokens_in,
                            "tokens_out": total_tokens_out,
                            "model": model,
                        }
                        tool_calls = _finalize_openai_tool_calls(tc_acc)
                        if tool_calls:
                            done_data["tool_calls"] = tool_calls
                        yield done_data
                        return
                    data = json.loads(raw)
                    usage = data.get("usage")
                    if usage:
                        total_tokens_in = usage.get("prompt_tokens", 0)
                        total_tokens_out = usage.get("completion_tokens", 0)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        _accumulate_openai_tool_delta(tc_acc, delta)
                        content = delta.get("content", "")
                        if content:
                            yield {"token": content, "done": False}

        done_data = {
            "token": "",
            "done": True,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "model": model,
        }
        tool_calls = _finalize_openai_tool_calls(tc_acc)
        if tool_calls:
            done_data["tool_calls"] = tool_calls
        yield done_data

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
            return [
                {
                    "name": m.get("id", ""),
                    "identifier": m.get("id", ""),
                    "parameters": {},
                }
                for m in data.get("data", [])
            ]
        except Exception as e:
            logger.warning("Failed to list OpenAI models: %s", e)
            return []

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False


# ── Anthropic Provider ─────────────────────────────


def _convert_messages_anthropic(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Convert internal message format to Anthropic format.

    Returns (system_prompt, messages). Anthropic requires the system prompt
    as a top-level parameter, not as a message. Images use source blocks.
    """
    system_prompt = None
    converted = []
    for msg in messages:
        role = msg["role"]
        if role == "system":
            system_prompt = msg.get("content", "")
            continue
        if role == "tool":
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": msg.get("content", ""),
                        }
                    ],
                }
            )
            continue

        images = msg.get("images")
        if images:
            content_parts = []
            for img_b64 in images:
                if img_b64.startswith("data:"):
                    media_type, _, b64data = img_b64.partition(";base64,")
                    media_type = media_type.replace("data:", "")
                else:
                    media_type = "image/png"
                    b64data = img_b64
                content_parts.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64data},
                    }
                )
            content_parts.append({"type": "text", "text": msg.get("content", "")})
            out = {"role": role, "content": content_parts}
        else:
            out = {"role": role, "content": msg.get("content", "")}

        if role == "assistant" and msg.get("tool_calls"):
            tool_use_blocks = []
            for tc in msg["tool_calls"]:
                tool_use_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc["name"],
                        "input": tc["arguments"]
                        if isinstance(tc["arguments"], dict)
                        else json.loads(tc["arguments"]),
                    }
                )
            if isinstance(out["content"], list):
                out["content"].extend(tool_use_blocks)
            else:
                out["content"] = [{"type": "text", "text": out["content"]}] + tool_use_blocks

        converted.append(out)
    return system_prompt, converted


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    ANTHROPIC_VERSION = "2023-06-01"

    # Fallback model list when /v1/models is not available
    KNOWN_MODELS = [
        "claude-sonnet-4-20250514",
        "claude-3-5-haiku-20241022",
        "claude-3-5-sonnet-20241022",
        "claude-3-opus-20240229",
        "claude-3-haiku-20240307",
    ]

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "anthropic-version": self.ANTHROPIC_VERSION,
        }
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    async def chat_completion(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        think: bool | str | None = None,  # Ollama-only; silently ignored here
    ) -> AsyncGenerator[dict, None]:
        system_prompt, converted = _convert_messages_anthropic(messages)
        payload: dict = {
            "model": model,
            "messages": converted,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            # Convert OpenAI-format tools to Anthropic format
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", t)
                anthropic_tools.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {}),
                    }
                )
            payload["tools"] = anthropic_tools

        total_tokens_in = 0
        total_tokens_out = 0
        tool_calls: list[dict] = []
        current_tool: dict | None = None

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/messages",
                json=payload,
                headers=self._headers(),
            ) as response:
                if response.status_code >= 400:
                    # Surface the upstream error BODY (e.g. the Claude CLI
                    # wrapper's {"detail": "claude CLI error: <real reason>"}),
                    # not just the bare status line — so a paused/failed lab
                    # shows WHY (rate limit vs overload vs context).
                    body = (await response.aread()).decode(errors="replace")[:600]
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code} from {self.base_url}: {body}",
                        request=response.request,
                        response=response,
                    )
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    data = json.loads(raw)
                    event_type = data.get("type", "")

                    if event_type == "message_start":
                        usage = data.get("message", {}).get("usage", {})
                        total_tokens_in = usage.get("input_tokens", 0)

                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool = {
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "arguments_str": "",
                            }

                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield {"token": text, "done": False}
                        elif delta.get("type") == "input_json_delta" and current_tool:
                            current_tool["arguments_str"] += delta.get("partial_json", "")

                    elif event_type == "content_block_stop":
                        if current_tool:
                            args_str = current_tool["arguments_str"]
                            try:
                                args = json.loads(args_str) if args_str else {}
                            except json.JSONDecodeError:
                                args = {"raw_arguments": args_str}
                            tool_calls.append(
                                {
                                    "id": current_tool["id"],
                                    "name": current_tool["name"],
                                    "arguments": args,
                                }
                            )
                            current_tool = None

                    elif event_type == "message_delta":
                        usage = data.get("usage", {})
                        total_tokens_out = usage.get("output_tokens", total_tokens_out)

        done_data: dict = {
            "token": "",
            "done": True,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "model": model,
        }
        if tool_calls:
            done_data["tool_calls"] = tool_calls
        yield done_data

    async def list_models(self) -> list[dict]:
        # Try the API first
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    if models:
                        return [
                            {
                                "name": m.get("id", ""),
                                "identifier": m.get("id", ""),
                                "parameters": {},
                            }
                            for m in models
                        ]
        except Exception:
            pass
        # Fallback to known models
        return [{"name": m, "identifier": m, "parameters": {}} for m in self.KNOWN_MODELS]

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/v1/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False


# ── Provider Factory ──────────────────────────────

# Cloud provider types that map to OpenAICompatibleProvider with preset base URLs
_OPENAI_COMPATIBLE_PRESETS = {
    "openai_cloud": "https://api.openai.com",
    "xai": "https://api.x.ai",
    "groq": "https://api.groq.com/openai",
    "deepseek": "https://api.deepseek.com",
}


def create_provider(provider_type: str, base_url: str, api_key: str | None = None) -> LLMProvider:
    """Create an LLM provider instance from type string."""
    if provider_type == "ollama":
        return OllamaProvider(base_url)
    elif provider_type == "huggingface":
        return HuggingFaceProvider(base_url, api_key)
    elif provider_type == "openai":
        return OpenAICompatibleProvider(base_url, api_key)
    elif provider_type == "claude_cli":
        # Per-server claude-cli wrapper (claude-cli/ at the repo root) —
        # speaks the OpenAI dialect, so the generic client fits as-is.
        return OpenAICompatibleProvider(base_url, api_key)
    elif provider_type == "anthropic":
        return AnthropicProvider(base_url, api_key)
    elif provider_type in _OPENAI_COMPATIBLE_PRESETS:
        url = base_url or _OPENAI_COMPATIBLE_PRESETS[provider_type]
        return OpenAICompatibleProvider(url, api_key)
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")
