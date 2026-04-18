from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict


class EventType(str, Enum):
    MODULE_ERROR = "MODULE_ERROR"
    AGENT_SPAWNED = "AGENT_SPAWNED"
    TASK_COMPLETED = "TASK_COMPLETED"
    HEARTBEAT_TICK = "HEARTBEAT_TICK"


@dataclass(slots=True)
class Event:
    event_type: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ModuleInfo:
    name: str
    capabilities: list[str] = field(default_factory=list)
    version: str = "0.0.1"


@dataclass(slots=True)
class Task:
    id: str
    description: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskResult:
    task_id: str
    output: dict[str, Any]
    success: bool = True
    error: str | None = None


class ArtifactPreview(TypedDict, total=False):
    url: str
    safe_inline: bool


class ArtifactRecord(TypedDict):
    artifact_id: str
    kind: str
    path: str
    mime_type: str
    title: str
    summary: str
    generator: str
    backend: str
    verified: bool
    provenance: dict[str, Any]
    preview: ArtifactPreview | None
