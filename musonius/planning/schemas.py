"""Pydantic models for the planning engine — Plan, Phase, FileChange."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class FileChange(BaseModel):
    """A single file modification within a plan phase."""

    path: str
    action: str = Field(description="create, modify, or delete")
    description: str
    key_changes: list[str] = Field(default_factory=list)


class Phase(BaseModel):
    """A single phase of an implementation plan."""

    id: str
    title: str
    description: str
    files: list[FileChange] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    test_strategy: str = ""
    estimated_tokens: int = 0


class Plan(BaseModel):
    """A complete implementation plan with one or more phases."""

    epic_id: str
    task_description: str
    phases: list[Phase] = Field(default_factory=list)
    total_estimated_tokens: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
