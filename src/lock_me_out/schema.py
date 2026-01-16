from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class LockSchedule(BaseModel):
    """Represents a scheduled lockout session."""

    id: UUID = Field(default_factory=uuid4)
    start_time: str
    end_time: str
    enabled: bool = True
    description: str | None = None
    persist: bool = False
    blocked_apps: list[str] = Field(default_factory=list)

    block_only: bool = False
