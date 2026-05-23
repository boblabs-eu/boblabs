"""Bob Manager — RAG ingestion helpers."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".sql",
    ".css",
    ".html",
    ".htm",
    ".xml",
}

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".sql",
}


def extract_text(file_path: Path, content_type: str | None = None) -> str:
    """Convert a supported file into plain text."""

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()

    raw = file_path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    if suffix in {".html", ".htm"} or (content_type or "").startswith("text/html"):
        return sanitize_html_document(text)

    if suffix == ".json" or (content_type or "") == "application/json":
        data = json.loads(text)
        lines: list[str] = []
        _flatten_json(data, prefix="", lines=lines)
        return "\n".join(lines)

    if suffix == ".csv" or (content_type or "") == "text/csv":
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for index, row in enumerate(reader, start=1):
            rendered = ", ".join(f"{key}={value}" for key, value in row.items())
            rows.append(f"row {index}: {rendered}")
        return "\n".join(rows)

    if suffix in TEXT_EXTENSIONS or not suffix:
        return text

    raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")


def sanitize_html_document(html: str) -> str:
    """Strip scripts and common page chrome while keeping readable structure."""

    cleaned_html = html
    try:
        from readability import Document as ReadabilityDocument

        cleaned_html = ReadabilityDocument(html).summary(html_partial=True)
    except Exception:
        cleaned_html = html

    soup = BeautifulSoup(cleaned_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def choose_splitter(file_path: Path, splitter: str) -> str:
    if splitter == "code":
        return "code"
    if splitter == "recursive" and file_path.suffix.lower() in CODE_EXTENSIONS:
        return "code"
    return splitter


def split_text(text: str, splitter: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into chunks using token-like approximations."""

    text = text.strip()
    if not text:
        return []

    target_chars = max(chunk_size * 4, 256)
    overlap_chars = max(chunk_overlap * 4, 0)

    if splitter == "fixed":
        return _fixed_split(text, target_chars, overlap_chars)
    if splitter == "sentence":
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return _join_units(sentences, target_chars, overlap_chars)
    if splitter == "paragraph":
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
        return _join_units(paragraphs, target_chars, overlap_chars)
    if splitter == "code":
        units = _split_code_units(text)
        return _join_units(units, target_chars, overlap_chars)
    return _recursive_split(text, target_chars, overlap_chars)


def _flatten_json(value, prefix: str, lines: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_json(item, next_prefix, lines)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            next_prefix = f"{prefix}[{index}]"
            _flatten_json(item, next_prefix, lines)
        return
    lines.append(f"{prefix}: {value}")


def _fixed_split(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + target_chars, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_len:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _join_units(units: list[str], target_chars: int, overlap_chars: int) -> list[str]:
    filtered = [unit.strip() for unit in units if unit and unit.strip()]
    if not filtered:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for unit in filtered:
        unit_len = len(unit) + 1
        if current and current_len + unit_len > target_chars:
            chunks.append("\n".join(current).strip())
            if overlap_chars > 0:
                overlap_units: list[str] = []
                overlap_len = 0
                for existing in reversed(current):
                    overlap_units.insert(0, existing)
                    overlap_len += len(existing) + 1
                    if overlap_len >= overlap_chars:
                        break
                current = overlap_units
                current_len = sum(len(part) + 1 for part in current)
            else:
                current = []
                current_len = 0

        if len(unit) > target_chars:
            for piece in _fixed_split(unit, target_chars, overlap_chars):
                if current:
                    chunks.append("\n".join(current).strip())
                    current = []
                    current_len = 0
                chunks.append(piece)
            continue

        current.append(unit)
        current_len += unit_len

    if current:
        chunks.append("\n".join(current).strip())
    return chunks


def _recursive_split(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= target_chars:
        return [text]

    separators = ["\n\n", "\n", ". ", " "]
    current = [text]

    for separator in separators:
        next_parts: list[str] = []
        changed = False
        for item in current:
            if len(item) <= target_chars:
                next_parts.append(item)
                continue
            if separator not in item:
                next_parts.append(item)
                continue
            parts = item.split(separator)
            rebuilt = []
            for part in parts:
                part = part.strip()
                if part:
                    rebuilt.append(part if separator == " " else part + separator.strip())
            if rebuilt:
                next_parts.extend(rebuilt)
                changed = True
            else:
                next_parts.append(item)
        current = next_parts
        if changed:
            current = _join_units(current, target_chars, overlap_chars)
            if all(len(item) <= target_chars for item in current):
                return current

    return _fixed_split(text, target_chars, overlap_chars)


def _split_code_units(text: str) -> list[str]:
    pattern = re.compile(
        r"(?=^(?:def |class |async def |function |\w+\s*=\s*\(|export (?:function|class)|const \w+\s*=\s*\()))",
        re.MULTILINE,
    )
    parts = [part.strip() for part in pattern.split(text) if part.strip()]
    return parts or [text]
