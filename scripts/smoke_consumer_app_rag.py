"""HMAC-level smoke test for the consumer-app RAG endpoints.

Exercises:
    /create_rag       (twice — idempotency)
    /list_rags
    /import_lab       (with rag_access block — round-trip)
    /grant_rag_access (with a separate ad-hoc lab)
    /revoke_rag_access
    /delete_rag       (both collections)

REQUIRED ENV (override defaults to match your prod / dev setup):

    BOB_API_URL       default: http://127.0.0.1:8888
    BOB_APP_ID        default: pouleapp
    BOB_APP_SECRET    no default — must be set

Run:

    BOB_APP_SECRET=<hex64> python3 scripts/smoke_consumer_app_rag.py

Exit code is 0 on full pass, 1 on the first failure. Output is line-prefixed
with PASS/FAIL/INFO so grep is easy.
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
BOB_APP_ID = os.environ.get("BOB_APP_ID", "pouleapp")
BOB_APP_SECRET = os.environ.get("BOB_APP_SECRET")

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
    r = httpx.post(url, content=body, headers=headers, timeout=30.0)
    if r.status_code >= 400:
        print(f"FAIL: {path} → HTTP {r.status_code}: {r.text}")
        sys.exit(1)
    return r.json()


def _call_expect_fail(path: str, payload: dict, expected_status: int) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = _sign(body)
    url = f"{BOB_API_URL}/api/v1/internal/apps{path}"
    r = httpx.post(url, content=body, headers=headers, timeout=30.0)
    if r.status_code != expected_status:
        print(f"FAIL: {path} expected HTTP {expected_status}, got {r.status_code}: {r.text}")
        sys.exit(1)
    return r.text


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    name_a = f"smoke_{suffix}_a"
    name_b = f"smoke_{suffix}_b"

    # 1) create_rag (first call)
    a = _call("/create_rag", {"name": name_a, "description": "smoke A"})
    print(f"PASS: create_rag {name_a} → id={a['collection_id']} full={a['collection_name']}")
    assert a["name"] == name_a, a
    assert a["collection_name"] == f"app__{BOB_APP_ID}__{name_a}", a

    # 2) create_rag (idempotency check — same args, same id)
    a2 = _call("/create_rag", {"name": name_a})
    if a2["collection_id"] != a["collection_id"]:
        print(
            f"FAIL: create_rag not idempotent — got {a2['collection_id']} vs {a['collection_id']}"
        )
        sys.exit(1)
    print("PASS: create_rag idempotent")

    # 3) second collection
    b = _call("/create_rag", {"name": name_b, "description": "smoke B"})
    print(f"PASS: create_rag {name_b} → id={b['collection_id']}")

    # 4) list_rags — both should appear
    listed = _call("/list_rags")
    names = {r["name"] for r in listed["rags"]}
    if name_a not in names or name_b not in names:
        print(f"FAIL: list_rags missing entries: got {sorted(names)}")
        sys.exit(1)
    print(f"PASS: list_rags returned {len(listed['rags'])} rag(s), incl. both smoke entries")

    # 5) import_lab — blueprint that references rag A via rag_access
    blueprint = {
        "version": 1,
        "lab": {
            "name": f"smoke_lab_{suffix}",
            "description": "smoke test lab for consumer-app RAG",
            "loop_type": "plan_execute",
            "orchestrator": {
                "model": "qwen3.6:35b-a3b",
                "prompt": "smoke test orchestrator",
                "temperature": 0.5,
            },
            "settings": {"max_iterations": 1, "max_duration_sec": 60},
            "agents": [
                {
                    "name": "smoke_agent",
                    "role": "smoke",
                    "system_prompt": "echo what you get",
                    "model": "qwen3.6:35b-a3b",
                    "temperature": 0.5,
                }
            ],
            "rag_access": [
                {"collection_name": a["collection_name"], "can_read": True, "can_write": False}
            ],
        },
    }
    imp = _call("/import_lab", {"blueprint": blueprint})
    lab_id = imp["lab_id"]
    print(f"PASS: import_lab created lab {lab_id} with rag_access")

    # 6) import_lab with cross-app rag — should 403
    bad_bp = json.loads(json.dumps(blueprint))
    bad_bp["lab"]["name"] = f"smoke_lab_bad_{suffix}"
    bad_bp["lab"]["rag_access"] = [
        {"collection_name": "app__some_other_app__nope", "can_read": True}
    ]
    _call_expect_fail("/import_lab", {"blueprint": bad_bp}, 403)
    print("PASS: import_lab rejects cross-app rag_access with 403")

    # 7) grant_rag_access — link rag B to the same lab via the imperative path
    granted = _call(
        "/grant_rag_access",
        {
            "lab_id": lab_id,
            "rag_name": name_b,
            "can_read": True,
            "can_write": True,
        },
    )
    if granted["collection_name"] != b["collection_name"]:
        print(f"FAIL: grant_rag_access returned wrong collection: {granted}")
        sys.exit(1)
    print(f"PASS: grant_rag_access linked {name_b} to lab {lab_id} (read+write)")

    # 8) revoke_rag_access
    revoked = _call("/revoke_rag_access", {"lab_id": lab_id, "rag_name": name_b})
    if not revoked["revoked"]:
        print(f"FAIL: revoke_rag_access did not remove the entry: {revoked}")
        sys.exit(1)
    print(f"PASS: revoke_rag_access removed {name_b} from lab {lab_id}")

    # 9) delete_rag — both
    for n in (name_a, name_b):
        d = _call("/delete_rag", {"name": n})
        if not d["deleted"]:
            print(f"FAIL: delete_rag {n} returned {d}")
            sys.exit(1)
    print(f"PASS: delete_rag cleaned up {name_a} and {name_b}")

    # 10) delete_rag again — should 404
    _call_expect_fail("/delete_rag", {"name": name_a}, 404)
    print("PASS: delete_rag on missing RAG returns 404")

    print("\nALL PASSED")


if __name__ == "__main__":
    main()
