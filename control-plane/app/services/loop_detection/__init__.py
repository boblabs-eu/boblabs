"""Anti-loop detection package.

Background-embedding loop detection that observes lab messages and triggers
recovery (pause → strip looping messages → resume) when repetitive behavior
is detected.

Public surface:
    - LoopManager: singleton, the only entrypoint that lab_runner uses
    - LoopReport, LoopSignal: dataclasses returned by detectors
    - LoopDetector (Protocol): pluggable detector contract

The embedder always runs as a fire-and-forget background task so the lab
iteration loop is never blocked.
"""
from .base import LoopDetector, LoopReport, LoopSignal, MessageRecord, ToolCall
from .manager import LoopManager, get_loop_manager

__all__ = [
    "LoopDetector",
    "LoopReport",
    "LoopSignal",
    "MessageRecord",
    "ToolCall",
    "LoopManager",
    "get_loop_manager",
]
