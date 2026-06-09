"""Web and browser tools: web_search, web_extract, browser_navigate, browser_snapshot, mermaid_to_img, excalidraw."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "web_search": {
        "description": "Search the web using DuckDuckGo. Returns a list of results with title, URL, and snippet.",
        "parameters": {
            "query": {"type": "string", "description": "Search query", "required": True},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "required": False,
            },
        },
    },
    "web_extract": {
        "description": "Fetch a web page URL and extract its text content. Returns the main text from the page.",
        "parameters": {
            "url": {
                "type": "string",
                "description": "The URL to fetch and extract content from",
                "required": True,
            },
        },
    },
    "browser_navigate": {
        "description": "Open a URL in a headless Chromium browser and return the page content as rendered text. Useful for JavaScript-heavy pages that need rendering.",
        "parameters": {
            "url": {"type": "string", "description": "The URL to navigate to", "required": True},
        },
    },
    "browser_snapshot": {
        "description": "Take a text snapshot of the current browser page (accessibility tree). Must call browser_navigate first.",
        "parameters": {},
    },
    "mermaid_to_img": {
        "description": "Convert a Mermaid diagram file (.mmd or .md with mermaid blocks) to an image (SVG or PNG). Returns the path to the generated file.",
        "parameters": {
            "input_path": {
                "type": "string",
                "description": "Path to the input .mmd or .md file (relative to workspace)",
                "required": True,
            },
            "output_format": {
                "type": "string",
                "description": "Output format: svg or png (default: svg)",
                "required": False,
            },
        },
    },
    "excalidraw": {
        "description": "Create an Excalidraw diagram from a JSON elements description. Saves the .excalidraw file, renders it to PNG via the browser, and uploads to excalidraw.com for a shareable link. Returns the saved file path and share URL.",
        "parameters": {
            "elements": {
                "type": "string",
                "description": "JSON array of Excalidraw element objects (rectangles, arrows, text, etc.). Use container binding for labels (boundElements + containerId), NOT the 'label' property.",
                "required": True,
            },
            "filename": {
                "type": "string",
                "description": "Output filename without extension (default: 'diagram')",
                "required": False,
            },
            "dark_mode": {
                "type": "string",
                "description": "Set to 'true' for dark background (default: false)",
                "required": False,
            },
        },
    },
}


from app.services.ssrf_guard import (
    PrivateHostError as _PrivateHostError,
)
from app.services.ssrf_guard import (
    is_private_host as _is_private_host,
)
from app.services.ssrf_guard import (
    safe_get as _ssrf_safe_get,
)

# Cluster E — the previous in-file helper missed IPv6, the full 127.0.0.0/8
# range, and treated 172.x.x.x as fully private even outside 172.16/12.
# Delegated to ssrf_guard.is_private_host which uses the ipaddress stdlib
# and re-validates redirect destinations via ssrf_guard.safe_get.


async def web_search(executor: ToolExecutor, args: dict) -> dict:
    query = args.get("query", "").strip()
    if not query:
        return {"success": False, "output": "web_search requires 'query'"}

    max_results = min(int(args.get("max_results", 5)), 10)

    from duckduckgo_search import DDGS

    try:

        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        results = await asyncio.get_event_loop().run_in_executor(None, _search)
    except Exception as e:
        return {"success": False, "output": f"Search failed: {e}"}

    if not results:
        return {"success": True, "output": "No results found."}

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("href", "")
        snippet = r.get("body", "")
        lines.append(f"{i}. **{title}**\n   {url}\n   {snippet}")
    return {"success": True, "output": "\n\n".join(lines)}


async def web_extract(executor: ToolExecutor, args: dict) -> dict:
    url = args.get("url", "").strip()
    if not url:
        return {"success": False, "output": "web_extract requires 'url'"}

    if not url.startswith(("http://", "https://")):
        return {"success": False, "output": "URL must start with http:// or https://"}

    from urllib.parse import urlparse

    hostname = urlparse(url).hostname or ""
    if _is_private_host(hostname):
        return {"success": False, "output": "Access to private/internal URLs is not allowed."}

    from bs4 import BeautifulSoup

    # Cluster E — manual redirect loop with per-hop private-host re-check.
    # ssrf_guard.safe_get refuses any Location header pointing into RFC1918,
    # IPv6 link-local / ULA, loopback, or docker container hostnames.
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            resp = await _ssrf_safe_get(
                client,
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                },
            )
            resp.raise_for_status()
    except _PrivateHostError as e:
        return {"success": False, "output": f"Refused fetch: {e}"}
    except Exception as e:
        return {"success": False, "output": f"Failed to fetch URL: {e}"}

    ct = resp.headers.get("content-type", "")
    if "html" not in ct and "text" not in ct:
        return {
            "success": True,
            "output": f"Non-HTML content ({ct}). First 2000 chars:\n{resp.text[:2000]}",
        }

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) > executor.max_output_bytes:
        text = text[: executor.max_output_bytes] + "\n... [truncated]"

    title = soup.title.get_text(strip=True) if soup.title else ""
    header = f"Title: {title}\nURL: {url}\n---\n" if title else f"URL: {url}\n---\n"
    return {"success": True, "output": header + text}


async def _sandbox_post(
    executor: ToolExecutor, endpoint: str, payload: dict, timeout: float = 60.0
) -> dict:
    """POST `payload` to a per-lab sandbox endpoint. Returns the JSON response.

    All browser tools route through the sandbox so headless Chromium runs in
    the lab-isolated container, never inside the control plane.
    """
    url = await executor.get_sandbox_url()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{url}{endpoint}", json=payload)
        resp.raise_for_status()
        return resp.json()


async def browser_navigate(executor: ToolExecutor, args: dict) -> dict:
    url = args.get("url", "").strip()
    if not url:
        return {"success": False, "output": "browser_navigate requires 'url'"}

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    if parsed.hostname and ("google.com" in parsed.hostname or "google." in parsed.hostname):
        if "/search" in parsed.path:
            qs = parse_qs(parsed.query)
            q = qs.get("q", [""])[0]
            if q:
                url = f"https://duckduckgo.com/?q={q}"

    hostname = urlparse(url).hostname or ""
    if _is_private_host(hostname):
        return {"success": False, "output": "Access to private/internal URLs is not allowed."}

    try:
        return await _sandbox_post(
            executor,
            "/browser_navigate",
            {"url": url, "max_output_kb": executor.max_output_bytes // 1024},
            timeout=45.0,
        )
    except Exception as e:
        return {"success": False, "output": f"Browser navigation failed: {e}"}


async def browser_snapshot(executor: ToolExecutor, args: dict) -> dict:
    try:
        return await _sandbox_post(
            executor,
            "/browser_snapshot",
            {"max_output_kb": executor.max_output_bytes // 1024},
            timeout=20.0,
        )
    except Exception as e:
        return {"success": False, "output": f"Browser snapshot failed: {e}"}


async def mermaid_to_img(executor: ToolExecutor, args: dict) -> dict:
    input_path = args.get("input_path", "").strip()
    if not input_path:
        return {"success": False, "output": "mermaid_to_img requires 'input_path'"}

    output_format = args.get("output_format", "svg").lower().strip()
    if output_format not in ("svg", "png"):
        return {"success": False, "output": "output_format must be svg or png"}

    clean_path = re.sub(r"^output/", "", input_path)

    target = None
    for base in (executor.workspace, executor.workspace / "output"):
        try:
            candidate = (base / clean_path).resolve()
            if candidate.is_relative_to(executor.workspace.resolve()) and candidate.is_file():
                target = candidate
                break
        except Exception:
            continue

    if target is None:
        return {"success": False, "output": f"Input file not found: {input_path}"}

    raw = target.read_text(errors="replace")

    diagrams: list[tuple[str, str]] = []
    stem = target.stem
    if target.suffix.lower() == ".md":
        blocks = re.findall(r"```mermaid\s*\n(.*?)```", raw, re.DOTALL)
        if not blocks:
            return {"success": False, "output": "No ```mermaid blocks found in markdown file."}
        for i, block in enumerate(blocks):
            diagrams.append((block.strip(), f"{stem}-{i + 1}"))
    else:
        diagrams.append((raw.strip(), stem))

    output_dir = executor.workspace / "output"
    output_dir.mkdir(exist_ok=True)
    generated_files: list[Path] = []

    try:
        for code, out_stem in diagrams:
            out_name = f"{out_stem}.{output_format}"
            out_path = output_dir / out_name

            escaped_code = code.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            html = f"""<!DOCTYPE html>
<html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
</head><body>
<div id="container"></div>
<script>
mermaid.initialize({{startOnLoad:false,theme:'default'}});
mermaid.render('diagram',`{escaped_code}`).then(({{svg}})=>{{
  document.getElementById('container').innerHTML=svg;
  document.getElementById('container').setAttribute('data-rendered','true');
}}).catch(err=>{{
  document.getElementById('container').textContent='ERROR: '+err.message;
  document.getElementById('container').setAttribute('data-error','true');
}});
</script>
</body></html>"""

            tmp_html = executor.workspace / "_mermaid_tmp.html"
            tmp_html.write_text(html)

            try:
                lab_id = str(executor.lab_id)
                if output_format == "svg":
                    result = await _sandbox_post(
                        executor,
                        "/browser_eval_selector",
                        {
                            "lab_id": lab_id,
                            "html_path": str(tmp_html.resolve()),
                            "wait_selector": "#container[data-rendered], #container[data-error]",
                            "error_selector": "#container[data-error]",
                            "selector": "#container svg",
                            "js_expression": "el => el.outerHTML",
                            "timeout_ms": 15000,
                        },
                        timeout=30.0,
                    )
                    if not result.get("success"):
                        return result
                    out_path.write_text(result.get("output", ""))
                else:
                    result = await _sandbox_post(
                        executor,
                        "/browser_screenshot_element",
                        {
                            "lab_id": lab_id,
                            "html_path": str(tmp_html.resolve()),
                            "output_path": str(out_path.resolve()),
                            "wait_selector": "#container[data-rendered], #container[data-error]",
                            "error_selector": "#container[data-error]",
                            "selector": "#container svg",
                            "timeout_ms": 15000,
                        },
                        timeout=30.0,
                    )
                    if not result.get("success"):
                        return result

                generated_files.append(out_path)
            finally:
                tmp_html.unlink(missing_ok=True)

        if not generated_files:
            return {"success": False, "output": "Mermaid conversion produced no output file."}

        if len(generated_files) == 1:
            f = generated_files[0]
            rel = f"output/{f.name}"
            return {
                "success": True,
                "output": f"Converted to {output_format}: {rel} ({f.stat().st_size} bytes)",
                "file_event": {"action": "created", "path": rel, "size_bytes": f.stat().st_size},
            }
        else:
            rel_paths = [f"output/{f.name}" for f in generated_files]
            size_total = sum(f.stat().st_size for f in generated_files)
            return {
                "success": True,
                "output": f"Mermaid diagrams converted ({len(generated_files)} files):\n"
                + "\n".join(rel_paths),
                "file_event": {"action": "created", "path": rel_paths[0], "size_bytes": size_total},
            }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "output": f"Mermaid conversion timed out after {executor.timeout_sec}s",
        }
    except Exception as e:
        return {"success": False, "output": f"Mermaid conversion error: {e}"}


async def _excalidraw_render_png(
    executor: ToolExecutor, doc_json: str, out_path: Path
) -> Path | None:
    """Render an Excalidraw JSON document to PNG via the per-lab sandbox browser."""
    escaped = doc_json.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    html = f"""<!DOCTYPE html>
<html><head>
<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@excalidraw/excalidraw/dist/excalidraw.production.min.js"></script>
<style>
  body {{ margin:0; padding:0; }}
  #root {{ width:1200px; height:800px; }}
</style>
</head><body>
<div id="root"></div>
<script>
const doc = JSON.parse(`{escaped}`);
const App = () => {{
  const [api, setApi] = React.useState(null);
  React.useEffect(() => {{
    if (api && doc.elements) {{
      api.updateScene({{ elements: doc.elements }});
      api.scrollToContent(api.getSceneElements(), {{ fitToContent: true }});
      setTimeout(() => {{
        document.getElementById('root').setAttribute('data-rendered', 'true');
      }}, 500);
    }}
  }}, [api]);
  return React.createElement(ExcalidrawLib.Excalidraw, {{
    initialData: {{ elements: doc.elements || [], appState: doc.appState || {{}} }},
    excalidrawAPI: (a) => setApi(a),
  }});
}};
ReactDOM.render(React.createElement(App), document.getElementById('root'));
</script>
</body></html>"""

    tmp_html = executor.workspace / "_excalidraw_tmp.html"
    tmp_html.write_text(html)

    try:
        result = await _sandbox_post(
            executor,
            "/browser_screenshot_element",
            {
                "lab_id": str(executor.lab_id),
                "html_path": str(tmp_html.resolve()),
                "output_path": str(out_path.resolve()),
                "wait_selector": "#root[data-rendered]",
                "selector": "#root",
                "timeout_ms": 25000,
            },
            timeout=45.0,
        )
        if not result.get("success"):
            return None
        return out_path
    finally:
        tmp_html.unlink(missing_ok=True)


async def _excalidraw_upload(doc_json: str) -> str | None:
    """Encrypt and upload Excalidraw JSON to excalidraw.com. Returns share URL."""
    import struct
    import urllib.request
    import zlib

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    UPLOAD_URL = "https://json.excalidraw.com/api/v2/post/"

    def concat_buffers(*buffers: bytes) -> bytes:
        parts = [struct.pack(">I", 1)]
        for buf in buffers:
            parts.append(struct.pack(">I", len(buf)))
            parts.append(buf)
        return b"".join(parts)

    file_metadata = json.dumps({}).encode("utf-8")
    data_bytes = doc_json.encode("utf-8")
    inner_payload = concat_buffers(file_metadata, data_bytes)

    compressed = zlib.compress(inner_payload)

    raw_key = os.urandom(16)
    iv = os.urandom(12)
    aesgcm = AESGCM(raw_key)
    encrypted = aesgcm.encrypt(iv, compressed, None)

    encoding_meta = json.dumps(
        {
            "version": 2,
            "compression": "pako@1",
            "encryption": "AES-GCM",
        }
    ).encode("utf-8")

    payload = concat_buffers(encoding_meta, iv, encrypted)

    loop = asyncio.get_event_loop()

    def _upload():
        req = urllib.request.Request(UPLOAD_URL, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Upload failed HTTP {resp.status}")
            return json.loads(resp.read().decode("utf-8"))

    result = await loop.run_in_executor(None, _upload)
    file_id = result.get("id")
    if not file_id:
        return None

    key_b64 = base64.urlsafe_b64encode(raw_key).rstrip(b"=").decode("ascii")
    return f"https://excalidraw.com/#json={file_id},{key_b64}"


async def excalidraw(executor: ToolExecutor, args: dict) -> dict:
    """Create an Excalidraw diagram, render to PNG, and upload for a share link."""
    elements_str = args.get("elements", "").strip()
    if not elements_str:
        return {
            "success": False,
            "output": "excalidraw requires 'elements' (JSON array of Excalidraw element objects)",
        }

    filename = args.get("filename", "diagram").strip() or "diagram"
    dark_mode = args.get("dark_mode", "").strip().lower() == "true"

    try:
        elements = json.loads(elements_str)
        if not isinstance(elements, list):
            return {"success": False, "output": "elements must be a JSON array"}
    except json.JSONDecodeError as e:
        return {"success": False, "output": f"Invalid JSON in elements: {e}"}

    bg_color = "#1e1e2e" if dark_mode else "#ffffff"
    doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "bob-manager",
        "elements": elements,
        "appState": {"viewBackgroundColor": bg_color},
    }
    doc_json = json.dumps(doc, indent=2)

    output_dir = executor.workspace / "output"
    output_dir.mkdir(exist_ok=True)

    excalidraw_path = output_dir / f"{filename}.excalidraw"
    excalidraw_path.write_text(doc_json)

    results = [f"Saved: output/{filename}.excalidraw"]

    try:
        png_path = await _excalidraw_render_png(executor, doc_json, output_dir / f"{filename}.png")
        if png_path:
            results.append(f"Rendered PNG: output/{filename}.png ({png_path.stat().st_size} bytes)")
    except Exception as e:
        logger.warning("Excalidraw PNG render failed: %s", e)
        results.append(f"PNG render skipped: {e}")

    try:
        share_url = await _excalidraw_upload(doc_json)
        if share_url:
            results.append(f"Share URL: {share_url}")
    except Exception as e:
        logger.warning("Excalidraw upload failed: %s", e)
        results.append(f"Upload skipped: {e}")

    return {
        "success": True,
        "output": "\n".join(results),
        "file_event": {
            "action": "created",
            "path": f"output/{filename}.excalidraw",
            "size_bytes": excalidraw_path.stat().st_size,
        },
    }


HANDLERS = {
    "web_search": web_search,
    "web_extract": web_extract,
    "browser_navigate": browser_navigate,
    "browser_snapshot": browser_snapshot,
    "mermaid_to_img": mermaid_to_img,
    "excalidraw": excalidraw,
}
