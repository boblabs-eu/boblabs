"""HMAC-level smoke test for the consumer-app agent + RAG-doc endpoints.

Exercises (signature-level only — does not require a working LLM provider
for the agent lifecycle calls, but /run_agent will obviously need one):

    /create_agent      (twice — idempotency)
    /list_agents
    /import_agent      (with rag_access — round-trip)
    /delete_agent      (cleanup)
    /update_rag        (display_name + description)
    /ingest_rag_document   (twice — second one with replace_if_exists=true)
    /list_rag_documents
    /delete_rag_document   (by filename)
    /create_rag + /delete_rag for setup/teardown

REQUIRED ENV:
    BOB_API_URL       default: http://127.0.0.1:8888
    BOB_APP_ID        default: smoke_recreate_test  (dedicated smoke app — avoid
                       pointing at a real app like pouleapp; the script creates
                       and tears down agents + rag collections under this id)
    BOB_APP_SECRET    no default — must be set, and must match BOB_APP_ID

Optional ENV — only needed if you also want to exercise /run_agent:
    BOB_SMOKE_RUN_AGENT_MODEL    model_identifier to attach to the smoke agent
    BOB_SMOKE_CALLBACK_URL       webhook receiver (e.g. local HTTP echo)

Run:
    BOB_APP_SECRET=<hex64> python3 scripts/smoke_consumer_app_agent.py

Exit code is 0 on full pass, 1 on the first failure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import httpx

BOB_API_URL = os.environ.get("BOB_API_URL", "http://127.0.0.1:8888").rstrip("/")
BOB_APP_ID = os.environ.get("BOB_APP_ID", "smoke_recreate_test")
BOB_APP_SECRET = os.environ.get("BOB_APP_SECRET")
RUN_AGENT_MODEL = os.environ.get("BOB_SMOKE_RUN_AGENT_MODEL", "").strip()
CALLBACK_URL = os.environ.get("BOB_SMOKE_CALLBACK_URL", "").strip()

if not BOB_APP_SECRET:
    print("FAIL: BOB_APP_SECRET env var is required")
    sys.exit(1)


def _sign(body: bytes) -> dict:
    ts = str(int(time.time()))
    msg = ts.encode() + b"." + body
    sig = hmac.new(BOB_APP_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-App-Id": BOB_APP_ID,
        "X-App-Timestamp": ts,
        "X-App-Signature": sig,
    }


def _call(path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload or {}, separators=(",", ":")).encode()
    headers = _sign(body)
    url = f"{BOB_API_URL}/api/v1/internal/apps{path}"
    r = httpx.post(url, content=body, headers=headers, timeout=60.0)
    if r.status_code >= 400:
        print(f"FAIL: {path} → HTTP {r.status_code}: {r.text}")
        sys.exit(1)
    return r.json()


def _call_expect_fail(path: str, payload: dict, expected: int) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = _sign(body)
    url = f"{BOB_API_URL}/api/v1/internal/apps{path}"
    r = httpx.post(url, content=body, headers=headers, timeout=30.0)
    if r.status_code != expected:
        print(f"FAIL: {path} expected HTTP {expected}, got {r.status_code}: {r.text}")
        sys.exit(1)
    return r.text


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    rag_name = f"smoke_rag_{suffix}"
    agent_a = f"smoke_agent_a_{suffix}"
    agent_b = f"smoke_agent_b_{suffix}"

    # ── Phase 1: agent CRUD ─────────────────────────────────────────────

    # Need a model id — use list_models to pick one if RUN_AGENT_MODEL is unset.
    models = _call("/list_models", {"available_only": True})
    if not models["models"]:
        print("FAIL: /list_models returned no available models — cannot create agent")
        sys.exit(1)
    smoke_model = RUN_AGENT_MODEL or models["models"][0]["model_identifier"]
    print(f"INFO: using model '{smoke_model}' for agent creation")

    a1 = _call(
        "/create_agent",
        {
            "name": agent_a,
            "system_prompt": "Echo what you are told.",
            "model": smoke_model,
            "temperature": 0.1,
            "max_tokens": 256,
        },
    )
    print(
        f"PASS: create_agent {agent_a} → id={a1['agent_id']} library_name={a1['library_agent_name']}"
    )
    assert a1["name"] == agent_a, a1
    assert a1["library_agent_name"] == f"app__{BOB_APP_ID}__{agent_a}", a1

    a1b = _call(
        "/create_agent",
        {
            "name": agent_a,
            "system_prompt": "should be ignored on idempotent path",
            "model": smoke_model,
        },
    )
    if a1b["agent_id"] != a1["agent_id"]:
        print(f"FAIL: create_agent not idempotent — got {a1b['agent_id']} vs {a1['agent_id']}")
        sys.exit(1)
    print("PASS: create_agent idempotent on (app_id, name)")

    listed = _call("/list_agents")
    names = {a["name"] for a in listed["agents"]}
    if agent_a not in names:
        print(f"FAIL: list_agents missing {agent_a}: got {sorted(names)}")
        sys.exit(1)
    print(f"PASS: list_agents returned {len(listed['agents'])} agent(s) incl. {agent_a}")

    # ── Phase 2: RAG collection for the round-trip ─────────────────────

    rag = _call("/create_rag", {"name": rag_name, "description": "agent smoke RAG"})
    print(f"PASS: create_rag {rag_name} → collection_name={rag['collection_name']}")

    # ── Phase 3: import_agent with rag_access (round-trip) ─────────────

    blueprint = {
        "version": 1,
        "agent": {
            "name": agent_b,
            "role": "support",
            "system_prompt": "Answer questions using rag_search.",
            "model": smoke_model,
            "temperature": 0.2,
            "max_tokens": 512,
            "rag_access": [
                {"collection_name": rag["collection_name"], "can_read": True, "can_write": False},
            ],
        },
    }
    b = _call("/import_agent", {"blueprint": blueprint})
    print(f"PASS: import_agent {agent_b} → id={b['agent_id']}")

    # Cross-app rag_access should 403
    bad_bp = json.loads(json.dumps(blueprint))
    bad_bp["agent"]["name"] = f"smoke_bad_{suffix}"
    bad_bp["agent"]["rag_access"] = [
        {"collection_name": "app__some_other_app__nope", "can_read": True}
    ]
    _call_expect_fail("/import_agent", {"blueprint": bad_bp}, 403)
    print("PASS: import_agent rejects cross-app rag_access with 403")

    # ── Phase 4: RAG document lifecycle ────────────────────────────────

    doc1 = _call(
        "/ingest_rag_document",
        {
            "name": rag_name,
            "filename": f"smoke_{suffix}.txt",
            "content": "Lorem ipsum dolor sit amet. " * 30,
        },
    )
    print(
        f"PASS: ingest_rag_document → status={doc1['status']} chunks={doc1['chunk_count']} replaced={doc1['replaced_previous']}"
    )
    assert not doc1["replaced_previous"], doc1

    doc2 = _call(
        "/ingest_rag_document",
        {
            "name": rag_name,
            "filename": f"smoke_{suffix}.txt",
            "content": "Replacement content. " * 50,
        },
    )
    if not doc2["replaced_previous"]:
        print(f"FAIL: second ingest_rag_document should have replaced_previous=true, got {doc2}")
        sys.exit(1)
    print(
        f"PASS: ingest_rag_document replaces by filename (chunks {doc1['chunk_count']} → {doc2['chunk_count']})"
    )

    listed_docs = _call("/list_rag_documents", {"name": rag_name})
    matching = [d for d in listed_docs["documents"] if d["filename"] == f"smoke_{suffix}.txt"]
    if len(matching) != 1:
        print(
            f"FAIL: expected exactly 1 doc with smoke filename, found {len(matching)}: {matching}"
        )
        sys.exit(1)
    print("PASS: list_rag_documents shows 1 doc for smoke filename (replace worked)")

    deleted = _call(
        "/delete_rag_document",
        {
            "name": rag_name,
            "filename": f"smoke_{suffix}.txt",
        },
    )
    if deleted["deleted"] != 1:
        print(f"FAIL: delete_rag_document expected 1 deleted, got {deleted}")
        sys.exit(1)
    print(f"PASS: delete_rag_document removed {deleted['deleted']} doc(s)")

    # ── Phase 5: update_rag ────────────────────────────────────────────

    updated = _call(
        "/update_rag",
        {
            "name": rag_name,
            "display_name": f"Smoke updated {suffix}",
            "description": "Updated description",
        },
    )
    assert updated["display_name"] == f"Smoke updated {suffix}", updated
    print(f"PASS: update_rag changed display_name → '{updated['display_name']}'")

    # ── Phase 6: run_agent (only when CALLBACK_URL is provided) ────────

    if CALLBACK_URL:
        run = _call(
            "/run_agent",
            {
                "name": agent_a,
                "generation_id": str(uuid.uuid4()),
                "callback_url": CALLBACK_URL,
                "user_message": "Say 'pong' and stop.",
            },
        )
        print(f"PASS: run_agent dispatched lab={run['lab_id']} status={run['status']}")

        # Poll list_agent_runs briefly to see the lab appear
        deadline = time.time() + 30.0
        seen = False
        while time.time() < deadline:
            runs = _call("/list_agent_runs", {"name": agent_a, "limit": 5})
            if any(r["lab_id"] == run["lab_id"] for r in runs["runs"]):
                seen = True
                break
            time.sleep(2)
        print(
            f"{'PASS' if seen else 'INFO'}: list_agent_runs {'saw' if seen else 'did not yet see'} the dispatched run"
        )
    else:
        print("INFO: skipping /run_agent (set BOB_SMOKE_CALLBACK_URL to exercise)")

    # ── Cleanup ────────────────────────────────────────────────────────

    for n in (agent_a, agent_b):
        d = _call("/delete_agent", {"name": n})
        if not d["deleted"]:
            print(f"FAIL: delete_agent {n} returned {d}")
            sys.exit(1)
    print(f"PASS: delete_agent cleaned up {agent_a}, {agent_b}")

    _call("/delete_rag", {"name": rag_name})
    print(f"PASS: delete_rag cleaned up {rag_name}")

    _call_expect_fail("/delete_agent", {"name": agent_a}, 404)
    print("PASS: delete_agent on missing agent returns 404")

    print("\nALL PASSED")


if __name__ == "__main__":
    main()
