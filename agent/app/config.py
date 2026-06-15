"""Bob Manager Agent — Configuration."""

import os


class AgentConfig:
    """Agent configuration loaded from environment variables."""

    agent_name: str = os.getenv("AGENT_NAME", "gpu-server")
    control_plane_urls: list[str] = [
        url.strip()
        for url in os.getenv("CONTROL_PLANE_URL", "ws://localhost:8000/ws/agent").split(",")
        if url.strip()
    ]
    agent_secret: str = os.getenv("AGENT_SECRET", "change-this-to-a-random-secret-token")
    metrics_port: int = int(os.getenv("METRICS_PORT", "9100"))
    heartbeat_interval: int = int(os.getenv("HEARTBEAT_INTERVAL", "30"))
    metrics_interval: int = int(os.getenv("METRICS_INTERVAL", "10"))
    script_runner_url: str = os.getenv("SCRIPT_RUNNER_URL", "http://localhost:9101")
    riffusion_url: str = os.getenv("RIFFUSION_URL", "http://localhost:3013")
    musicgen_url: str = os.getenv("MUSICGEN_URL", "http://localhost:3014")
    bark_url: str = os.getenv("BARK_URL", "http://localhost:3015")
    rvc_url: str = os.getenv("RVC_URL", "http://localhost:3016")
    coqui_tts_url: str = os.getenv("COQUI_TTS_URL", "http://localhost:3017")
    stt_url: str = os.getenv("STT_URL", "http://localhost:7865")
    ltx_video_url: str = os.getenv("LTX_VIDEO_URL", "http://localhost:3018")
    wan_video_url: str = os.getenv("WAN_VIDEO_URL", "http://localhost:3019")
    comfyui_url: str = os.getenv("COMFYUI_URL", "http://localhost:8188")
    claude_cli_url: str = os.getenv("CLAUDE_CLI_URL", "http://localhost:3021")


config = AgentConfig()
