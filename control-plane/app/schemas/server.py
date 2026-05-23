"""Bob Manager — Server Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ServerBase(BaseModel):
    """Shared server fields."""
    name: str
    host: str
    port: int = 9100


class ServerCreate(ServerBase):
    """Schema for creating a server."""
    pass


class ServerUpdate(BaseModel):
    """Schema for updating a server."""
    name: str | None = None
    host: str | None = None
    port: int | None = None


class ServerResponse(ServerBase):
    """Schema returned from API."""
    id: UUID
    status: str
    os_info: dict
    gpu_info: dict
    last_heartbeat: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ServerMetrics(BaseModel):
    """Real-time metrics snapshot from an agent."""
    cpu_usage: float
    cpu_temperature: float | None = None
    gpu_usage: float | None = None
    gpu_temperature: float | None = None
    ram_total: int
    ram_used: int
    ram_percent: float
    network_bytes_sent: int
    network_bytes_recv: int
    disk_total: int
    disk_used: int
    disk_percent: float
