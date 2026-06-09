"""Bob Manager — Tool Executor.

Executes tool calls made by lab agents. Dispatches to domain-specific
tool modules (tools/tool_*.py) discovered automatically at import time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))

# ── Tool registry: auto-discovered from app.services.tools package ──────
from app.services.tools import BUILTIN_TOOLS, TOOL_HANDLERS  # noqa: E402

# Regex to find tool calls in agent responses
TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)

# Lenient: <tool_call> without closing tag (model forgot </tool_call>)
TOOL_CALL_OPEN_RE = re.compile(
    r"<tool_call>\s*(\{.+)",
    re.DOTALL,
)

# XML-style: <tool_call><function=name><parameter=key>value</parameter>...</function></tool_call>
TOOL_CALL_XML_RE = re.compile(
    r"<tool_call>\s*<function=(\w+)>(.*?)</function>\s*</tool_call>",
    re.DOTALL,
)

# XML parameter extraction: <parameter=key>value</parameter>
XML_PARAM_RE = re.compile(
    r"<parameter=(\w+)>(.*?)</parameter>",
    re.DOTALL,
)

# Extract fenced code blocks
CODE_BLOCK_RE = re.compile(r"```\w*\n(.*?)```", re.DOTALL)

# Fallback regex: detect implicit "Save as: filename" at the end of a response
# Matches patterns like "Save as: file.md", "Saved as: file.txt", "File saved: out.py"
SAVE_AS_RE = re.compile(
    r'(?:^|\n)\s*(?:---\s*\n)?\s*(?:save(?:d)?\s+as|file\s+saved)\s*[:.]\s*[`"\']?'
    r'([\w./-]+\.\w{1,10})[`"\']?\s*$',
    re.IGNORECASE | re.MULTILINE,
)

# __all__ for backward-compatible imports
__all__ = [
    "BUILTIN_TOOLS",
    "ToolExecutor",
    "parse_tool_calls",
    "format_tool_descriptions",
    "build_native_tools_schema",
]


def _extract_balanced_json(text: str) -> str | None:
    """Extract the first balanced JSON object from *text*."""
    depth = 0
    start = None
    in_string = False
    escape_next = False
    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if in_string:
            if ch == "\\":
                escape_next = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : i + 1]
    return None


def _repair_tool_json(raw_json: str, full_content: str) -> str | None:
    """Fix common invalid-JSON patterns produced by LLMs.

    Handles:
      - "content": code       (bare variable → substitute last code block)
      - "code": open(...)     (Python expression → convert to string)
    Returns repaired JSON string or None.
    """
    # --- bare variable for "content" field in file_write ---
    m = re.search(r'("content"\s*:\s*)([a-zA-Z_]\w*)(\s*\})', raw_json)
    if m:
        # Get code blocks from full response, skip blocks containing <tool_call>
        blocks = [b for b in CODE_BLOCK_RE.findall(full_content) if "<tool_call>" not in b]
        if blocks:
            code_content = blocks[-1]
            escaped = json.dumps(code_content)
            fixed = raw_json[: m.start(2)] + escaped + raw_json[m.end(2) :]
            try:
                json.loads(fixed)
                return fixed
            except json.JSONDecodeError:
                pass

    # --- Python expression for "code" field (open("file").read()) ---
    m = re.search(r'("code"\s*:\s*)(open\([^)]+\)[^}]*)', raw_json)
    if m:
        # Extract filename from open("filename"...)
        fname = re.search(r'open\(["\']([^"\']+)', m.group(2))
        if fname:
            replacement = json.dumps(f"exec(open('{fname.group(1)}').read())")
            fixed = raw_json[: m.start(2)] + replacement + raw_json[m.end(2) :]
            try:
                json.loads(fixed)
                return fixed
            except json.JSONDecodeError:
                pass

    return None


def _try_parse_tool_call(raw_json: str, full_content: str) -> dict | None:
    """Try to parse a single tool-call JSON, with repair fallback."""
    for attempt_json in (raw_json, _repair_tool_json(raw_json, full_content)):
        if attempt_json is None:
            continue
        try:
            data = json.loads(attempt_json)
            name = data.get("name", "")
            args = data.get("arguments", {})
            if name:
                return {"name": name, "arguments": args}
        except json.JSONDecodeError:
            pass
    return None


def parse_tool_calls(content: str, agent_tools: list[str] | None = None) -> list[dict]:
    """Extract tool calls from agent response text.

    Returns list of {"name": str, "arguments": dict}.

    Strategy (in order):
    1a. Match <tool_call>...JSON...</tool_call>  (standard format)
    1b. Match <tool_call><function=name><parameter=k>v</parameter>...</function></tool_call> (XML format)
    1c. Same as 1b without closing </tool_call> tag
    2.  Match <tool_call>...JSON without closing tag (model forgot </tool_call>)
    3.  Fallback: detect implicit "Save as: filename" patterns
    """
    calls = []

    # Preprocess: strip comment prefixes from tool_call tags
    # Models sometimes write "# <tool_call>" inside code blocks
    cleaned = re.sub(r"#\s*(</?tool_call>)", r"\1", content)

    # --- Strategy 1: standard <tool_call>...</tool_call> ---
    for match in TOOL_CALL_RE.finditer(cleaned):
        parsed = _try_parse_tool_call(match.group(1), cleaned)
        if parsed:
            calls.append(parsed)
        else:
            logger.warning("Failed to parse tool call JSON: %s", match.group(1)[:200])

    # --- Strategy 1b: XML-style <tool_call><function=name><parameter=...>...</tool_call> ---
    if not calls:
        for match in TOOL_CALL_XML_RE.finditer(cleaned):
            func_name = match.group(1)
            body = match.group(2)
            args = {}
            for pm in XML_PARAM_RE.finditer(body):
                key = pm.group(1)
                val = pm.group(2).strip()
                # Try to parse value as JSON (for nested objects like params)
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    pass
                args[key] = val
            logger.info("Parsed XML-format tool call: %s(%s)", func_name, list(args.keys()))
            calls.append({"name": func_name, "arguments": args})

    # --- Strategy 1c: XML-style without closing </tool_call> ---
    if not calls:
        xml_open = re.finditer(
            r"<tool_call>\s*<function=(\w+)>(.*?)</function>",
            cleaned,
            re.DOTALL,
        )
        for match in xml_open:
            func_name = match.group(1)
            body = match.group(2)
            args = {}
            for pm in XML_PARAM_RE.finditer(body):
                key = pm.group(1)
                val = pm.group(2).strip()
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    pass
                args[key] = val
            logger.info("Parsed open XML-format tool call: %s(%s)", func_name, list(args.keys()))
            calls.append({"name": func_name, "arguments": args})

    # --- Strategy 2: <tool_call> without closing tag ---
    if not calls:
        for match in TOOL_CALL_OPEN_RE.finditer(cleaned):
            json_str = _extract_balanced_json(match.group(1))
            if json_str:
                parsed = _try_parse_tool_call(json_str, cleaned)
                if parsed:
                    calls.append(parsed)
                else:
                    logger.warning("Failed to parse open tool call JSON: %s", json_str[:200])

    # --- Strategy 3: implicit "Save as: filename" ---
    if not calls and agent_tools and "file_write" in agent_tools:
        save_match = SAVE_AS_RE.search(content)
        if save_match:
            filename = save_match.group(1)
            # Extract content: everything before the "Save as:" line
            file_content = content[: save_match.start()].rstrip()
            # Strip trailing "---" separator if present
            if file_content.endswith("---"):
                file_content = file_content[:-3].rstrip()
            if file_content:
                logger.info(
                    "Implicit file_write detected: %s (%d bytes)", filename, len(file_content)
                )
                calls.append(
                    {
                        "name": "file_write",
                        "arguments": {"path": filename, "content": file_content},
                    }
                )

    return calls


def _build_pipeline_description(pipeline_names: list[str]) -> str:
    """Build dynamic media_pipeline description for selected pipelines."""
    from app.services.pipelines import PIPELINE_REGISTRY

    parts = []
    for name in pipeline_names:
        cls = PIPELINE_REGISTRY.get(name)
        if cls:
            instance = cls("http://placeholder")
            parts.append(instance.tool_description())
        else:
            parts.append(f"{name} — unknown pipeline")
    base = "Generate media (audio, image, video) using GPU-accelerated pipelines."
    if parts:
        base += " Available: " + "; ".join(parts) + "."
    return base


def format_tool_descriptions(tool_names: list[str]) -> str:
    """Build tool description text for injection into agent system prompt."""
    from app.services.pipelines import (
        extract_pipeline_names,
        extract_subtool_permissions,
        normalize_tool_names,
    )

    if not tool_names:
        return ""

    # Extract pipeline sub-selections before normalizing
    selected_pipelines = extract_pipeline_names(tool_names)
    subtool_perms = extract_subtool_permissions(tool_names)
    normalized = normalize_tool_names(tool_names)

    lines = [
        "\n## Available Tools",
        "",
        "You MUST call tools by including a <tool_call> block in your response.",
        "Do NOT just mention a filename — you MUST use the tool_call block to actually create files.",
        "",
        "<tool_call>",
        '{"name": "tool_name", "arguments": {"key": "value"}}',
        "</tool_call>",
        "",
    ]

    # Add a concrete file_write example if the agent has that tool
    if "file_write" in normalized:
        lines += [
            "Example — to save a file, you MUST use:",
            "",
            "<tool_call>",
            '{"name": "file_write", "arguments": {"path": "my_output.md", "content": "# Title\\nFile content here..."}}',
            "</tool_call>",
            "",
        ]

    lines += [
        "You may make multiple tool calls in a single response.",
        "After all tools execute, you will receive their results and can continue.",
        "Only call tools when needed — you can also respond normally without tools.",
        "",
        "### Tools:",
        "",
    ]

    for name in normalized:
        if name == "media_pipeline" and selected_pipelines:
            # Dynamic description with selected pipelines
            desc = _build_pipeline_description(selected_pipelines)
            tool = BUILTIN_TOOLS["media_pipeline"]
            params = tool["parameters"]
            param_strs = []
            for pname, pinfo in params.items():
                req = " (required)" if pinfo.get("required") else ""
                if pname == "pipeline":
                    # Restrict to selected pipelines
                    param_strs.append(
                        f"pipeline: string (required) — one of: {', '.join(selected_pipelines)}"
                    )
                else:
                    param_strs.append(f"{pname}: {pinfo['type']}{req}")
            lines.append(f"- **{name}**({', '.join(param_strs)}): {desc}")
            continue

        # Dynamic action constraint for expandable tools (mail, twitter, trading, defi_data, web3_portfolio)
        allowed_actions = subtool_perms.get(name)
        if (
            name in ("mail", "twitter", "trading", "defi_data", "web3_portfolio")
            and allowed_actions
        ):
            tool = BUILTIN_TOOLS[name]
            action_str = ", ".join(allowed_actions)
            desc = tool["description"] + f" Allowed actions: {action_str}."
            params = tool["parameters"]
            param_strs = []
            for pname, pinfo in params.items():
                req = " (required)" if pinfo.get("required") else ""
                if pname == "action":
                    param_strs.append(f"action: string (required) — one of: {action_str}")
                else:
                    param_strs.append(f"{pname}: {pinfo['type']}{req}")
            lines.append(f"- **{name}**({', '.join(param_strs)}): {desc}")
            continue

        tool = BUILTIN_TOOLS.get(name)
        if not tool:
            continue
        params = tool["parameters"]
        param_strs = []
        for pname, pinfo in params.items():
            req = " (required)" if pinfo.get("required") else ""
            param_strs.append(f"{pname}: {pinfo['type']}{req}")
        lines.append(f"- **{name}**({', '.join(param_strs)}): {tool['description']}")

    # Inject Excalidraw reference when the tool is available
    if "excalidraw" in normalized:
        lines.append("")
        lines.append("### Excalidraw Quick Reference")
        lines.append(
            "- elements: JSON array of element objects (rectangle, ellipse, diamond, arrow, text)"
        )
        lines.append(
            '- **CRITICAL**: Use container binding for labels: shape needs `boundElements: [{"id": "t_id", "type": "text"}]`, text needs `containerId: "shape_id"`. Do NOT use `"label"` property — it doesn\'t exist.'
        )
        lines.append(
            "- Always include `fontFamily: 1`, `originalText`, `autoResize: true` on text elements"
        )
        lines.append(
            '- Arrow bindings: `startBinding/endBinding: { "elementId": "id", "fixedPoint": [x, y] }` where right=[1,0.5], left=[0,0.5], top=[0.5,0], bottom=[0.5,1]'
        )
        lines.append(
            "- Colors: Blue=#a5d8ff, Green=#b2f2bb, Orange=#ffd8a8, Purple=#d0bfff, Red=#ffc9c9, Yellow=#fff3bf, Teal=#c3fae8"
        )
        lines.append(
            "- Min font: 16 body, 20 titles. Min shape: 120x60. Z-order: first=back, last=front"
        )

    lines.append("")
    return "\n".join(lines)


def build_native_tools_schema(tool_names: list[str]) -> list[dict]:
    """Convert BUILTIN_TOOLS to OpenAI function-calling schema for native tool calling.

    Works with Ollama (0.3+), vLLM, and OpenAI-compatible APIs.
    Handles media_pipeline:* and mail:*/twitter:* sub-selections.
    """
    from app.services.pipelines import (
        extract_pipeline_names,
        extract_subtool_permissions,
        normalize_tool_names,
    )

    selected_pipelines = extract_pipeline_names(tool_names)
    subtool_perms = extract_subtool_permissions(tool_names)
    normalized = normalize_tool_names(tool_names)

    schemas = []
    for name in normalized:
        tool = BUILTIN_TOOLS.get(name)
        if not tool:
            continue

        # Dynamic description for media_pipeline
        description = tool["description"]
        if name == "media_pipeline" and selected_pipelines:
            description = _build_pipeline_description(selected_pipelines)

        # Dynamic action constraint for expandable tools (mail, twitter, trading, defi_data, web3_portfolio)
        allowed_actions = subtool_perms.get(name)

        properties = {}
        required = []
        for pname, pinfo in tool["parameters"].items():
            prop = {
                "type": pinfo["type"],
                "description": pinfo["description"],
            }
            # Constrain pipeline param to selected pipelines
            if name == "media_pipeline" and pname == "pipeline" and selected_pipelines:
                prop["enum"] = selected_pipelines
                prop["description"] = f"Pipeline to use. One of: {', '.join(selected_pipelines)}"
            # Constrain action param for expandable tools
            if (
                name in ("mail", "twitter", "trading", "defi_data", "web3_portfolio")
                and pname == "action"
                and allowed_actions
            ):
                prop["enum"] = allowed_actions
                prop["description"] = f"Action to perform. One of: {', '.join(allowed_actions)}"
            properties[pname] = prop
            if pinfo.get("required"):
                required.append(pname)

        desc = description
        if (
            name in ("mail", "twitter", "trading", "defi_data", "web3_portfolio")
            and allowed_actions
        ):
            desc += f" Allowed actions: {', '.join(allowed_actions)}."

        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return schemas


class ToolExecutor:
    """Execute tool calls for a lab with safety limits."""

    def __init__(
        self,
        lab_id: UUID,
        db: AsyncSession,
        timeout_sec: int = 60,
        max_output_kb: int = 256,
        container_memory_mb: int = 512,
        call_agent_handler: Any | None = None,
        allowed_pipelines: list[str] | None = None,
        subtool_permissions: dict[str, list[str]] | None = None,
    ):
        self.lab_id = lab_id
        self.db = db
        self.timeout_sec = timeout_sec
        self.max_output_bytes = max_output_kb * 1024
        self.container_memory_mb = container_memory_mb
        self._call_agent_handler = call_agent_handler
        self._subtool_permissions = subtool_permissions or {}
        self._allowed_pipelines = allowed_pipelines or self._subtool_permissions.get(
            "media_pipeline", []
        )
        self.workspace = LAB_RESOURCES_ROOT / str(lab_id)
        self.workspace.mkdir(parents=True, exist_ok=True)
        # Ensure output subdirectory exists
        (self.workspace / "output").mkdir(exist_ok=True)
        # Ensure symlinks exist for UUID-prefixed resource files
        self._ensure_resource_symlinks()
        # Clock timers state: {name: {"start": datetime, "elapsed": float, "running": bool}}
        self._timers: dict[str, dict] = {}

    def _ensure_resource_symlinks(self):
        """Create symlinks from original_name to UUID-prefixed resource files.

        Resource files are stored as '<uuid8>_<original_name>' on disk but agents
        know them by original_name only.  Symlinks let imports and execution work.
        """
        import re as _re

        for f in self.workspace.iterdir():
            if f.is_file() and not f.name.startswith("_") and not f.is_symlink():
                m = _re.match(r"^[0-9a-f]{8}_(.+)$", f.name)
                if m:
                    link = self.workspace / m.group(1)
                    if not link.exists():
                        try:
                            link.symlink_to(f.name)
                        except OSError:
                            pass

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """Execute a single tool call. Returns {"success": bool, "output": str}."""
        handler = TOOL_HANDLERS.get(tool_name)

        if not handler:
            return {"success": False, "output": f"Unknown tool: {tool_name}"}

        # Long-running tools get extended timeouts
        _SLOW_TOOL_TIMEOUTS = {
            "media_pipeline": 1800,
            "video_generate": 600,
            "youtube": 330,
            "audio_mix": 180,
            "image_generate": 180,
        }
        effective_timeout = max(self.timeout_sec, _SLOW_TOOL_TIMEOUTS.get(tool_name, 0))

        try:
            result = await asyncio.wait_for(
                handler(self, arguments),
                timeout=effective_timeout,
            )
            # Truncate output
            if len(result.get("output", "")) > self.max_output_bytes:
                result["output"] = (
                    result["output"][: self.max_output_bytes] + "\n... [output truncated]"
                )
            return result
        except asyncio.TimeoutError:
            return {
                "success": False,
                "output": f"Tool '{tool_name}' timed out after {effective_timeout}s",
            }
        except Exception as e:
            logger.exception("Tool '%s' failed for lab %s", tool_name, self.lab_id)
            return {"success": False, "output": f"Tool error: {str(e)}"}

    async def get_sandbox_url(self) -> str:
        """Get per-lab sandbox URL, creating the container if needed.

        The sandbox container hosts python_exec, shell_exec AND the headless
        Chromium used by browser_* / mermaid_to_img / excalidraw, so all
        untrusted execution is confined to the per-lab sandbox.
        """
        from app.services.container_manager import ensure_sandbox

        return await ensure_sandbox(self.lab_id, memory_mb=self.container_memory_mb)
