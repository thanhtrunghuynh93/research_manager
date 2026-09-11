"""Enums shared across modules. Module-specific enums live in that module's models.py."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    PROF = "prof"
    STUDENT = "student"


class Visibility(StrEnum):
    PROFESSOR_ONLY = "professor_only"
    STUDENT_PRIVATE = "student_private"
    PROJECT_SHARED = "project_shared"


class ActorKind(StrEnum):
    USER = "user"
    SYSTEM = "system"
    JOB = "job"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
