"""SQLAlchemy models package.

Importing this package registers every model with ``Base.metadata``,
which Alembic's autogenerate and the startup schema-verification check
both rely on to know the full set of expected tables.
"""
from app.models.base import Base
from app.models.conversation import Conversation
from app.models.file import File
from app.models.relationship import Relationship
from app.models.report import Report
from app.models.repository import Repository
from app.models.repository_intelligence import RepositoryIntelligence
from app.models.repository_workspace import RepositoryWorkspace
from app.models.symbol import Symbol

__all__ = [
    "Base",
    "Repository",
    "RepositoryWorkspace",
    "RepositoryIntelligence",
    "File",
    "Symbol",
    "Relationship",
    "Report",
    "Conversation",
]
