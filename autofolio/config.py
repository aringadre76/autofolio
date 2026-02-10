from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator


class ProjectConfig(BaseModel):
    title: str
    description: str
    repo_url: str
    demo_url: str = ""
    tech_stack: list[str] = []
    tags: list[str] = []

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v.strip()

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("description must not be empty")
        return v.strip()


class Evaluation(BaseModel):
    portfolio_priority: Literal["top", "middle", "bottom"]
    resume_worthy: bool
    reason: str


class PlannedAction(BaseModel):
    path: str
    action: Literal["create", "replace", "append", "insert_after_line", "insert_before_line"]
    explain: str


class AnalysisResponse(BaseModel):
    evaluation: Evaluation
    files_to_read: list[str]
    plan: list[PlannedAction]


class PatchAction(BaseModel):
    path: str
    action: Literal["create", "replace", "append", "insert_after_line", "insert_before_line"]
    insert_after_marker: str | None = None
    target_line: int | None = None
    content: str


class GenerationResponse(BaseModel):
    patch: list[PatchAction]
    resume_snippet: str | None = None


LLM_PROVIDER = Literal["ollama", "openai"]

DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def load_project_config(path: str | Path) -> ProjectConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ProjectConfig(**data)
