"""Bob Manager — Module, Step, and Task Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ── Theme Colors ────────────────────────────────
class ThemeColorResponse(BaseModel):
    name: str
    color: str

    class Config:
        from_attributes = True


class ThemeColorUpdate(BaseModel):
    color: str


# ── Modules ─────────────────────────────────────
class ModuleBase(BaseModel):
    name: str
    description: str = ""
    position: int = 0


class ModuleCreate(ModuleBase):
    pass


class ModuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    position: int | None = None


class ModuleResponse(ModuleBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Steps ───────────────────────────────────────
class StepBase(BaseModel):
    name: str
    description: str = ""
    step_order: int = 0
    status: str = "not-started"
    included_task_ids: list[str] = []


class StepCreate(StepBase):
    pass


class StepUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    step_order: int | None = None
    status: str | None = None
    included_task_ids: list[str] | None = None


class StepResponse(StepBase):
    id: UUID
    module_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Tasks ───────────────────────────────────────
class DependencyRef(BaseModel):
    type: str  # "task" or "module"
    id: str


class TaskBase(BaseModel):
    name: str
    description: str = ""
    status: str = "not-started"
    deadline: datetime | None = None
    dependencies: list[DependencyRef] = []


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    deadline: datetime | None = None
    dependencies: list[DependencyRef] | None = None


class TaskResponse(TaskBase):
    id: UUID
    module_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Enriched Module response with steps & tasks ─
class ModuleDetailResponse(ModuleResponse):
    steps: list[StepResponse] = []
    tasks: list[TaskResponse] = []
