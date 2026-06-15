"""Standalone unit tests for the claude-cli wrapper's pure functions.

Run from claude-cli/:  python3 -m pytest tests/ -v
(only needs fastapi installed; no claude binary, no network)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from main import (  # noqa: E402
    MODEL_PREFIX,
    configured_models,
    flatten_messages,
    namespaced_models,
    strip_prefix,
)

# ── Model list (env-driven, never hardcoded) ──────────────────────────


def test_default_models_from_env_default(monkeypatch):
    monkeypatch.delenv("CLAUDE_CLI_MODELS", raising=False)
    assert configured_models() == ["haiku", "opus", "sonnet"]
    assert namespaced_models() == ["claude-cli:haiku", "claude-cli:opus", "claude-cli:sonnet"]


def test_env_overrides_model_list(monkeypatch):
    monkeypatch.setenv("CLAUDE_CLI_MODELS", " claude-opus-4-8 , haiku ")
    assert configured_models() == ["claude-opus-4-8", "haiku"]
    assert namespaced_models() == ["claude-cli:claude-opus-4-8", "claude-cli:haiku"]


def test_strip_prefix_accepts_both_forms():
    assert strip_prefix(f"{MODEL_PREFIX}opus") == "opus"
    assert strip_prefix("opus") == "opus"
    assert strip_prefix(f"{MODEL_PREFIX}claude-opus-4-8") == "claude-opus-4-8"


# ── Message flattening ────────────────────────────────────────────────


def test_single_user_message_passes_verbatim():
    sp, prompt = flatten_messages(
        [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "say hi"},
        ]
    )
    assert sp == "You are concise."
    assert prompt == "say hi"


def test_multiple_system_messages_joined():
    sp, _ = flatten_messages(
        [
            {"role": "system", "content": "Rule A."},
            {"role": "system", "content": "Rule B."},
            {"role": "user", "content": "hello"},
        ]
    )
    assert sp == "Rule A.\n\nRule B."


def test_history_flattens_to_transcript():
    _, prompt = flatten_messages(
        [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "And times 3?"},
        ]
    )
    assert prompt.startswith("Conversation so far:")
    assert "User: What is 2+2?" in prompt
    assert "Assistant: 4" in prompt
    assert "User: And times 3?" in prompt
    assert prompt.rstrip().endswith("with no role label.")


def test_multimodal_content_keeps_text_drops_images():
    _, prompt = flatten_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
                ],
            }
        ]
    )
    assert prompt == "describe this"


def test_tool_role_kept_as_transcript_line():
    _, prompt = flatten_messages(
        [
            {"role": "user", "content": "run it"},
            {"role": "tool", "content": "exit 0", "tool_call_id": "call_1"},
            {"role": "user", "content": "now summarize"},
        ]
    )
    assert "Tool result: exit 0" in prompt


def test_empty_messages_give_empty_prompt():
    """No conversational content → empty prompt so the route can 400."""
    sp, prompt = flatten_messages([])
    assert sp == ""
    assert prompt == ""

    sp, prompt = flatten_messages([{"role": "system", "content": "only rules"}])
    assert sp == "only rules"
    assert prompt == ""
