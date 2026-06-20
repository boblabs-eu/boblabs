"""Lab-resource <-> Hermes file bridge.

A Hermes agent runs in its OWN container with ONLY its private ``bob-hermes-<id>``
volume mounted — it cannot see ``lab_resources`` (that physical isolation is the
point; see ``ADAPTER_CONTRACT.md`` and the runtime module). So files cross the
boundary as bytes over the adapter's ``/v1/agent/run`` call:

- **Inbound** (operator → agent): ``build_resource_payload`` reads the lab's
  uploaded resources off the shared ``lab_resources`` volume (bob-api has it
  mounted) and base64-encodes them for the request. The adapter materializes them
  inside the agent's own container at ``~/.hermes/bob_io/inputs/``.
- **Outbound** (agent → operator): the adapter returns whatever the agent wrote to
  ``~/.hermes/bob_io/outputs/`` and ``persist_hermes_outputs`` drops it into the
  lab's ``output/`` dir, where the existing OUTPUTS panel + download endpoint
  (``api/routes/labs_files.py``) surface it — no new UI.

Both directions are size-capped; anything over the cap is skipped and logged
(never silently truncated).
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

# Mirror of the constant used across the control-plane (lab_runner, tool_executor,
# labs routes). bob-api mounts the shared lab_resources volume here.
LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))

_MB = 1024 * 1024
# Inbound: the upload endpoint already caps a single file at 20 MB
# (labs_files.py), so per-file matches that; total bounds the request body.
MAX_INPUT_FILE_BYTES = 20 * _MB
MAX_INPUT_TOTAL_BYTES = 30 * _MB
# Outbound: bound the adapter's reply body.
MAX_OUTPUT_FILE_BYTES = 20 * _MB
MAX_OUTPUT_TOTAL_BYTES = 50 * _MB


def _safe_name(name: str) -> str:
    """Strip any directory component — defeats ``../`` / absolute-path tricks."""
    return os.path.basename((name or "").strip())


def build_resource_payload(
    resources,
    *,
    max_file_bytes: int = MAX_INPUT_FILE_BYTES,
    max_total_bytes: int = MAX_INPUT_TOTAL_BYTES,
) -> list[dict]:
    """Read a lab's uploaded ``LabResource`` rows off disk into a wire payload.

    Returns ``[{"name", "content_b64", "size_bytes"}]`` (``name`` is the
    user-facing ``original_name``). Files that are missing, unreadable, or over a
    cap are omitted and logged — the agent simply won't be told about them.
    """
    payload: list[dict] = []
    total = 0
    for res in resources or []:
        original = _safe_name(getattr(res, "original_name", "") or getattr(res, "filename", ""))
        if not original:
            continue
        path = LAB_RESOURCES_ROOT / str(res.lab_id) / res.filename
        try:
            if not path.is_file():
                logger.warning("Hermes input resource missing on disk: %s", path)
                continue
            size = path.stat().st_size
            if size > max_file_bytes:
                logger.warning(
                    "Hermes input resource '%s' skipped: %d bytes > %d cap",
                    original,
                    size,
                    max_file_bytes,
                )
                continue
            if total + size > max_total_bytes:
                logger.warning(
                    "Hermes input resource '%s' skipped: total payload would exceed %d cap",
                    original,
                    max_total_bytes,
                )
                continue
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("Hermes input resource '%s' unreadable: %s", original, exc)
            continue
        total += len(data)
        payload.append(
            {
                "name": original,
                "content_b64": base64.b64encode(data).decode("ascii"),
                "size_bytes": len(data),
            }
        )
    return payload


def persist_hermes_outputs(
    lab_id: UUID | str,
    outputs,
    *,
    max_file_bytes: int = MAX_OUTPUT_FILE_BYTES,
    max_total_bytes: int = MAX_OUTPUT_TOTAL_BYTES,
) -> list[str]:
    """Write files the agent produced into the lab's ``output/`` dir.

    ``outputs`` is the adapter's ``[{"name", "content_b64", "size_bytes"?}]`` list,
    where ``name`` is a path RELATIVE to the agent's workspace (e.g.
    ``project/renders/out.mp4``). Files land under
    ``LAB_RESOURCES_ROOT/<lab_id>/output/<relpath>`` (structure preserved) so the
    existing ``GET /{lab_id}/output-files`` listing + download endpoint pick them up
    with no new wiring. Returns the relpaths written (for logging / the lab message).
    """
    if not outputs:
        return []
    out_dir = LAB_RESOURCES_ROOT / str(lab_id) / "output"
    out_root = out_dir.resolve()
    written: list[str] = []
    total = 0
    for item in outputs:
        if not isinstance(item, dict):
            continue
        rel = (item.get("name") or "").strip().lstrip("/")
        b64 = item.get("content_b64")
        if not rel or not isinstance(b64, str):
            continue
        try:
            data = base64.b64decode(b64)
        except (ValueError, TypeError) as exc:
            logger.warning("Hermes output '%s' not valid base64: %s", rel, exc)
            continue
        if len(data) > max_file_bytes:
            logger.warning(
                "Hermes output '%s' skipped: %d bytes > %d cap", rel, len(data), max_file_bytes
            )
            continue
        if total + len(data) > max_total_bytes:
            logger.warning("Hermes output '%s' skipped: total exceeds %d cap", rel, max_total_bytes)
            continue
        # Traversal guard: the resolved target must stay under output/.
        target = (out_dir / rel).resolve()
        if not target.is_relative_to(out_root):
            logger.warning("Hermes output '%s' rejected: path escapes output dir", rel)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            logger.warning("Could not write Hermes output '%s': %s", rel, exc)
            continue
        total += len(data)
        written.append(rel)
    if written:
        logger.info("Persisted %d Hermes output file(s) to lab %s: %s", len(written), lab_id, written)
    return written
