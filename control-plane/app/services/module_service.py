"""Bob Manager — Module service layer (modules, steps, tasks)."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.module import ModuleStep, ModuleTask, ProjectModule
from app.schemas.module import (
    ModuleCreate,
    ModuleUpdate,
    StepCreate,
    StepUpdate,
    TaskCreate,
    TaskUpdate,
)


class ModuleService:
    """Business logic for project modules, steps, and tasks."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Modules ──────────────────────────────────
    async def list_modules(self, project_id: UUID) -> list[ProjectModule]:
        result = await self.db.execute(
            select(ProjectModule)
            .where(ProjectModule.project_id == project_id)
            .order_by(ProjectModule.position, ProjectModule.created_at)
        )
        return list(result.scalars().all())

    async def get_module(self, module_id: UUID) -> ProjectModule | None:
        result = await self.db.execute(select(ProjectModule).where(ProjectModule.id == module_id))
        return result.scalar_one_or_none()

    async def create_module(self, project_id: UUID, data: ModuleCreate) -> ProjectModule:
        mod = ProjectModule(
            project_id=project_id,
            name=data.name,
            description=data.description,
            position=data.position,
        )
        self.db.add(mod)
        await self.db.flush()
        await self.db.refresh(mod)
        return mod

    async def update_module(self, module_id: UUID, data: ModuleUpdate) -> ProjectModule | None:
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return await self.get_module(module_id)
        await self.db.execute(
            update(ProjectModule).where(ProjectModule.id == module_id).values(**updates)
        )
        await self.db.flush()
        return await self.get_module(module_id)

    async def delete_module(self, module_id: UUID) -> bool:
        mod = await self.get_module(module_id)
        if mod:
            await self.db.delete(mod)
            await self.db.flush()
            return True
        return False

    # ── Steps ────────────────────────────────────
    async def list_steps(self, module_id: UUID) -> list[ModuleStep]:
        result = await self.db.execute(
            select(ModuleStep)
            .where(ModuleStep.module_id == module_id)
            .order_by(ModuleStep.step_order)
        )
        return list(result.scalars().all())

    async def get_step(self, step_id: UUID) -> ModuleStep | None:
        result = await self.db.execute(select(ModuleStep).where(ModuleStep.id == step_id))
        return result.scalar_one_or_none()

    async def create_step(self, module_id: UUID, data: StepCreate) -> ModuleStep:
        step = ModuleStep(
            module_id=module_id,
            name=data.name,
            description=data.description,
            step_order=data.step_order,
            status=data.status,
            included_task_ids=data.included_task_ids,
        )
        self.db.add(step)
        await self.db.flush()
        await self.db.refresh(step)
        return step

    async def update_step(self, step_id: UUID, data: StepUpdate) -> ModuleStep | None:
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return await self.get_step(step_id)
        await self.db.execute(update(ModuleStep).where(ModuleStep.id == step_id).values(**updates))
        await self.db.flush()
        return await self.get_step(step_id)

    async def delete_step(self, step_id: UUID) -> bool:
        step = await self.get_step(step_id)
        if step:
            await self.db.delete(step)
            await self.db.flush()
            return True
        return False

    # ── Tasks ────────────────────────────────────
    async def list_tasks(self, module_id: UUID) -> list[ModuleTask]:
        result = await self.db.execute(
            select(ModuleTask)
            .where(ModuleTask.module_id == module_id)
            .order_by(ModuleTask.created_at)
        )
        return list(result.scalars().all())

    async def get_task(self, task_id: UUID) -> ModuleTask | None:
        result = await self.db.execute(select(ModuleTask).where(ModuleTask.id == task_id))
        return result.scalar_one_or_none()

    async def create_task(self, module_id: UUID, data: TaskCreate) -> ModuleTask:
        deps = [d.model_dump() for d in data.dependencies] if data.dependencies else []
        task = ModuleTask(
            module_id=module_id,
            name=data.name,
            description=data.description,
            status=data.status,
            deadline=data.deadline,
            dependencies=deps,
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def update_task(self, task_id: UUID, data: TaskUpdate) -> ModuleTask | None:
        updates = data.model_dump(exclude_unset=True)
        if "dependencies" in updates and updates["dependencies"] is not None:
            updates["dependencies"] = [
                d if isinstance(d, dict) else d.model_dump() for d in updates["dependencies"]
            ]
        if not updates:
            return await self.get_task(task_id)
        await self.db.execute(update(ModuleTask).where(ModuleTask.id == task_id).values(**updates))
        await self.db.flush()
        return await self.get_task(task_id)

    async def delete_task(self, task_id: UUID) -> bool:
        task = await self.get_task(task_id)
        if task:
            await self.db.delete(task)
            await self.db.flush()
            return True
        return False
