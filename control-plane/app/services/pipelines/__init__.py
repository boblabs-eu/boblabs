"""Bob Manager — Media generation pipelines.

Modular, abstracted pipelines for non-LLM model inference
(audio, image, video generation).
"""

from app.services.pipelines.bark import BarkPipeline
from app.services.pipelines.base import MediaPipeline, PipelineResult
from app.services.pipelines.coqui_tts import CoquiTTSPipeline
from app.services.pipelines.ltx_video import LTXVideoPipeline
from app.services.pipelines.musicgen import MusicGenPipeline
from app.services.pipelines.riffusion import RiffusionPipeline
from app.services.pipelines.rvc import RVCPipeline
from app.services.pipelines.stt import STTPipeline
from app.services.pipelines.wan_video import WanVideoPipeline

# Registry: provider_type -> pipeline class
PIPELINE_REGISTRY: dict[str, type[MediaPipeline]] = {
    "riffusion": RiffusionPipeline,
    "musicgen": MusicGenPipeline,
    "bark": BarkPipeline,
    "rvc": RVCPipeline,
    "coqui_tts": CoquiTTSPipeline,
    "stt": STTPipeline,
    "ltx_video": LTXVideoPipeline,
    "wan_video": WanVideoPipeline,
}


def is_media_pipeline(provider_type: str) -> bool:
    """Check if a provider_type is a media pipeline (not an LLM)."""
    return provider_type in PIPELINE_REGISTRY


def get_pipeline(provider_type: str, base_url: str) -> MediaPipeline:
    """Create a pipeline instance by provider type."""
    cls = PIPELINE_REGISTRY.get(provider_type)
    if cls is None:
        raise ValueError(f"No pipeline registered for provider type: {provider_type}")
    return cls(base_url)


def get_available_pipelines() -> list[dict]:
    """Return metadata for all registered pipelines.

    Used by the API to show which pipelines exist for tool configuration.
    """
    result = []
    for name, cls in PIPELINE_REGISTRY.items():
        # Instantiate with dummy URL just to read class-level metadata
        instance = cls("http://placeholder")
        result.append(
            {
                "name": name,
                "description": instance.tool_description(),
            }
        )
    return result


# Tools that use colon-delimited sub-selections (tool_name:sub_name)
EXPANDABLE_TOOLS = {
    "media_pipeline",
    "mail",
    "twitter",
    "youtube",
    "trading",
    "defi_data",
    "web3_portfolio",
    "media_post",
}


def extract_pipeline_names(tool_names: list[str]) -> list[str]:
    """Extract pipeline sub-selections from a tool name list.

    e.g. ['think', 'media_pipeline:riffusion', 'media_pipeline:cogvideo']
    returns ['riffusion', 'cogvideo']
    """
    prefix = "media_pipeline:"
    return [n[len(prefix) :] for n in tool_names if n.startswith(prefix)]


def extract_subtool_permissions(tool_names: list[str]) -> dict[str, list[str]]:
    """Extract sub-tool permissions for all expandable tools.

    e.g. ['mail:read', 'mail:send', 'twitter:read', 'media_pipeline:riffusion']
    returns {'mail': ['read', 'send'], 'twitter': ['read'], 'media_pipeline': ['riffusion']}
    """
    result: dict[str, list[str]] = {}
    for name in tool_names:
        if ":" in name:
            parent, sub = name.split(":", 1)
            if parent in EXPANDABLE_TOOLS:
                result.setdefault(parent, []).append(sub)
    return result


def normalize_tool_names(tool_names: list[str]) -> list[str]:
    """Replace expandable_tool:* entries with a single 'expandable_tool' entry.

    Returns a new list suitable for tool permission checks.
    e.g. ['think', 'media_pipeline:riffusion', 'mail:read'] -> ['think', 'media_pipeline', 'mail']

    Also expands the MCP server token ``mcp:<slug>`` into that server's currently
    registered ``mcp__<slug>__<tool>`` names, so an agent can be granted a whole
    MCP server the same way it is granted a tool-set. Concrete ``mcp__…`` names
    (double underscore, no colon) pass through unchanged.
    """
    # Lazy import — avoids any import cycle with the tools package at module load.
    from app.services.tools import BUILTIN_TOOLS
    from app.services.tools.mcp_registry import mcp_server_tool_keys

    result = []
    seen_parents: set[str] = set()
    for name in tool_names:
        if name.startswith("mcp:"):
            rest = name[len("mcp:") :]
            if ":" in rest:
                # 'mcp:<slug>:<tool>' (written by the SubToolGroup picker) → the
                # single namespaced tool key.
                slug, tool = rest.split(":", 1)
                key = f"mcp__{slug}__{tool}"
                if key in BUILTIN_TOOLS and key not in result:
                    result.append(key)
            else:
                # 'mcp:<slug>' → the whole server's currently-registered tools.
                for key in mcp_server_tool_keys(rest):
                    if key not in result:
                        result.append(key)
            continue
        if ":" in name:
            parent = name.split(":", 1)[0]
            if parent in EXPANDABLE_TOOLS and parent not in seen_parents:
                result.append(parent)
                seen_parents.add(parent)
        else:
            result.append(name)
    return result


__all__ = [
    "MediaPipeline",
    "PipelineResult",
    "RiffusionPipeline",
    "MusicGenPipeline",
    "BarkPipeline",
    "CoquiTTSPipeline",
    "RVCPipeline",
    "STTPipeline",
    "PIPELINE_REGISTRY",
    "EXPANDABLE_TOOLS",
    "is_media_pipeline",
    "get_pipeline",
    "get_available_pipelines",
    "extract_pipeline_names",
    "extract_subtool_permissions",
    "normalize_tool_names",
]
