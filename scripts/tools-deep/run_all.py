"""Aggregator: copy ``scripts/tools-deep/`` into bob-api and run every test_*.

Run from the repo root::

    python scripts/tools-deep/run_all.py

Each ``test_<tool>.py`` runs in its own Python invocation inside the
container. Verdicts (PASS / FAIL / SKIPPED) are aggregated into
``docs/TOOL_TEST_REPORT_DEEP.md``.

Exit code:
    0  — every test was PASS or SKIPPED.
    1  — at least one test FAILed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DOCS_REPORT = REPO / "docs" / "TOOL_TEST_REPORT_DEEP.md"
CONTAINER_DIR = "/tmp/tools-deep"
CONTAINER_REPORT = "/tmp/tool-test-report-deep.md"

# Order matters only for readability of the final report.
ORDER = [
    "test_mail_send.py",
    "test_twitter_post.py",
    "test_postiz.py",
    "test_trustless_otc.py",
    "test_image_gen.py",
    "test_audio_gen.py",
    "test_video_gen.py",
    "test_media_post.py",
    "test_trading_send.py",
    "test_rag_ingest.py",
    "test_call_agent.py",
    "test_media_pipeline.py",
]


def _docker(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], **kw)


def _copy_into_container() -> None:
    # Reset the container-side report so we accumulate fresh results.
    _docker(["exec", "-T", "bob-api", "rm", "-f", CONTAINER_REPORT], check=False)
    _docker(["exec", "-T", "bob-api", "mkdir", "-p", CONTAINER_DIR], check=True)
    # ``docker compose cp`` copies the directory contents under a trailing /.
    _docker(["cp", str(HERE) + "/.", f"bob-api:{CONTAINER_DIR}"], check=True)


_FORWARDED_ENV_PREFIXES = (
    "MAIL_",
    "TWITTER_",
    "MEDIA_POST_",
    "TRADING_TEST_",
    "RAG_TEST_",
    "PIPELINE_",
    "AUDIO_GEN_",
    "BOB_ALLOW_",
)


def _run_one(script: str) -> tuple[str, str]:
    """Return (verdict, output_line)."""
    # Forward any test-relevant env from host into the container.
    env_args: list[str] = ["-e", f"PYTHONPATH=/app:{CONTAINER_DIR}"]
    import os as _os

    for k, v in _os.environ.items():
        if any(k.startswith(p) for p in _FORWARDED_ENV_PREFIXES):
            env_args += ["-e", f"{k}={v}"]
    cp = _docker(
        ["exec", "-T", *env_args, "bob-api", "python", f"{CONTAINER_DIR}/{script}"],
        capture_output=True,
        text=True,
    )
    output = (cp.stdout or "").strip().splitlines()
    result_line = next((l for l in reversed(output) if l.startswith(("RESULT:", "MISSING"))), "")
    if not result_line:
        # No structured line — bubble up the last line of stderr/stdout for the report.
        last = (cp.stderr or cp.stdout or "(no output)").strip().splitlines()[-1:][0:1]
        return "FAIL", f"{script}: {last[0] if last else 'no output'}"
    if result_line.startswith("MISSING"):
        return "SKIPPED", f"{script}: {result_line}"
    m = re.match(r"RESULT:\s+\S+\s+(\w+)\s*(?:—\s*(.*))?", result_line)
    if not m:
        return "FAIL", f"{script}: unparseable: {result_line}"
    return m.group(1), result_line


def main() -> int:
    if shutil.which("docker") is None:
        print("docker not found in PATH", file=sys.stderr)
        return 2

    _copy_into_container()

    results: list[tuple[str, str, str]] = []
    for script in ORDER:
        if not (HERE / script).exists():
            results.append((script, "MISSING", f"{script}: file not in {HERE}"))
            continue
        print(f"→ {script}", flush=True)
        verdict, line = _run_one(script)
        print(f"  {line}")
        results.append((script, verdict, line))

    counts = {"PASS": 0, "FAIL": 0, "SKIPPED": 0, "MISSING": 0}
    for _, verdict, _ in results:
        counts[verdict] = counts.get(verdict, 0) + 1

    DOCS_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with DOCS_REPORT.open("w") as f:
        f.write("# Tool Deep Test Report\n\n")
        f.write("Run via `scripts/tools-deep/run_all.py` against the live bob-api container. ")
        f.write("Each script tests one tool's full path including secret-required calls.\n\n")
        f.write("## Summary\n\n")
        f.write("| Verdict | Count |\n|---|---|\n")
        for v in ("PASS", "FAIL", "SKIPPED", "MISSING"):
            f.write(f"| {v} | {counts.get(v, 0)} |\n")
        f.write("\n## Results\n\n")
        f.write("| Script | Verdict | Output |\n|---|---|---|\n")
        for script, verdict, line in results:
            safe = line.replace("|", "\\|")
            f.write(f"| `{script}` | {verdict} | {safe} |\n")
    print(f"\nReport: {DOCS_REPORT}")
    return 1 if counts.get("FAIL", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
