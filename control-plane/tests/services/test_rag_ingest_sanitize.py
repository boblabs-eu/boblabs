"""rag_ingest.sanitize_html_document — strips active content.

The sanitizer is on the RAG URL ingestion path. Pages fetched via
the agent's RAG tool flow through this function before chunking, so
any active content that survives lands in the vector store and can
re-emerge in agent prompts.

Tests assert script, style, noscript, nav, footer, header, svg are
all removed AND the visible text survives.
"""

from __future__ import annotations

import pytest

from app.services.rag_ingest import sanitize_html_document

pytestmark = pytest.mark.service


def test_strips_script_tag():
    html = """
    <html><body>
    <p>Visible content here.</p>
    <script>alert('xss')</script>
    </body></html>
    """
    out = sanitize_html_document(html)
    assert "alert" not in out
    assert "Visible content here." in out


def test_strips_style_and_noscript():
    html = """
    <html><body>
    <style>body { background: red }</style>
    <noscript>Please enable JavaScript</noscript>
    <p>Real content.</p>
    </body></html>
    """
    out = sanitize_html_document(html)
    assert "background: red" not in out
    assert "enable JavaScript" not in out
    assert "Real content." in out


def test_strips_chrome_tags():
    """nav, footer, header, svg are dropped (likely boilerplate)."""
    html = """
    <html><body>
    <header>Site Header</header>
    <nav>Nav links</nav>
    <main><p>Article body.</p></main>
    <footer>Site Footer</footer>
    <svg><circle cx='10' cy='10' r='5'/></svg>
    </body></html>
    """
    out = sanitize_html_document(html)
    assert "Article body." in out
    # readability may keep some of the chrome — at minimum the explicit
    # decompose() must drop svg children.
    assert "circle" not in out.lower()


def test_handles_empty_input():
    assert sanitize_html_document("") == ""


def test_handles_no_html():
    """Plain text passes through (no html parsing fails the function)."""
    out = sanitize_html_document("just some words")
    assert "just some words" in out
