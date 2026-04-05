"""Minimal runtime settings for the operator shell."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from memory.checkpoints import OperatorAutonomyMode


class ShellSettings(BaseModel):
    """Operator shell defaults."""

    model_config = ConfigDict(extra="forbid")

    default_mode: OperatorAutonomyMode = OperatorAutonomyMode.MANUAL


class AutoSafeSettings(BaseModel):
    """Explicitly narrow policy for auto-safe rollback execution."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    allowed_base_urls: list[str] = Field(default_factory=list)


class AutonomySettings(BaseModel):
    """Autonomy mode settings."""

    model_config = ConfigDict(extra="forbid")

    auto_safe: AutoSafeSettings = Field(default_factory=AutoSafeSettings)


class RuntimeSettings(BaseModel):
    """Repository-local runtime settings."""

    model_config = ConfigDict(extra="forbid")

    shell: ShellSettings = Field(default_factory=ShellSettings)
    autonomy: AutonomySettings = Field(default_factory=AutonomySettings)


def load_runtime_settings(path: Path) -> RuntimeSettings:
    """Load runtime settings or return safe defaults when no file exists."""

    if not path.exists():
        return RuntimeSettings()

    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        return RuntimeSettings.model_validate(payload)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        msg = f"invalid runtime settings at {path}: {exc}"
        raise ValueError(msg) from exc
