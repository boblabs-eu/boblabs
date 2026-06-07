"""Bob Manager — SQLAlchemy ORM models package.

D08 — every model gets re-exported here so callers can do
``from app.models import Lab`` (or any other) without having to know
the per-file submodule path. Keeps Base.metadata complete for
alembic autogenerate too.
"""

from app.models.access_token import AccessToken, QuoteRequest, TrialRequest
from app.models.base import Base
from app.models.blog_post import BlogPost, BlogToken
from app.models.consumer_app import ConsumerApp
from app.models.execution import CommandHistory, ExecutionLog, WorkflowExecution
from app.models.module import ModuleStep, ModuleTask, ProjectModule
from app.models.orchestrator import (
    AIAgent,
    AIModel,
    AIProvider,
    Conversation,
    CronJob,
    GpuLock,
    Lab,
    LabAgent,
    LabMemory,
    LabMessage,
    LabResource,
    LabScheduleLog,
    LabTool,
    LibraryAgent,
    LlmEvent,
    Message,
    OrchestratorSettings,
    OrchestratorTask,
    PromptTemplate,
    ToolConfig,
    ToolSet,
)
from app.models.platform_settings import PlatformSettings
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.project import Project
from app.models.rag import LabRagAccess, RagCollection, RagDocument
from app.models.request_log import RequestLog
from app.models.resource import Resource, ResourceProject
from app.models.server import LabServerAccess, Server
from app.models.theme_color import ThemeColor
from app.models.trading import TradeHistory, TradingPosition
from app.models.wallet import LabWeb3Access, Wallet
from app.models.web3_settings import Web3Settings
from app.models.workflow import Workflow, WorkflowStep


__all__ = [
    # Base
    "Base",
    # Access tokens + requests
    "AccessToken",
    "QuoteRequest",
    "TrialRequest",
    # Blog
    "BlogPost",
    "BlogToken",
    # Consumer apps (HMAC)
    "ConsumerApp",
    # Execution / workflow history
    "CommandHistory",
    "ExecutionLog",
    "WorkflowExecution",
    # Modules
    "ModuleStep",
    "ModuleTask",
    "ProjectModule",
    # Orchestrator + labs
    "AIAgent",
    "AIModel",
    "AIProvider",
    "Conversation",
    "CronJob",
    "GpuLock",
    "Lab",
    "LabAgent",
    "LabMemory",
    "LabMessage",
    "LabResource",
    "LabScheduleLog",
    "LabTool",
    "LibraryAgent",
    "LlmEvent",
    "Message",
    "OrchestratorSettings",
    "OrchestratorTask",
    "PromptTemplate",
    "ToolConfig",
    "ToolSet",
    # Platform / settings
    "PlatformSettings",
    "PortfolioSnapshot",
    # Projects + resources
    "Project",
    "Resource",
    "ResourceProject",
    # RAG
    "LabRagAccess",
    "RagCollection",
    "RagDocument",
    # Observability
    "RequestLog",
    # Servers
    "LabServerAccess",
    "Server",
    # Theming
    "ThemeColor",
    # Trading
    "TradeHistory",
    "TradingPosition",
    # Wallets + web3
    "LabWeb3Access",
    "Wallet",
    "Web3Settings",
    # Workflows
    "Workflow",
    "WorkflowStep",
]
