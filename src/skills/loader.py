"""Helpers for locating and validating repository-managed skill assets."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from skills.models import SkillAsset, SkillMetadata

_FRONTMATTER_DELIMITER = "+++"


class SkillLoadError(ValueError):
    """Raised when a skill asset cannot be parsed or validated."""


@dataclass(slots=True)
class SkillLoader:
    """Loads `SKILL.md` assets with TOML frontmatter metadata."""

    root: Path

    def discover(self) -> tuple[str, ...]:
        if not self.root.exists():
            return ()
        return tuple(
            sorted(
                path.name
                for path in self.root.iterdir()
                if self.skill_path(path.name).exists()
            )
        )

    def skill_path(self, skill_name: str) -> Path:
        return self.root / skill_name / "SKILL.md"

    def load(self, skill_name: str) -> SkillAsset:
        path = self.skill_path(skill_name)
        if not path.exists():
            msg = f"skill asset not found: {path}"
            raise SkillLoadError(msg)

        raw_text = path.read_text(encoding="utf-8")
        frontmatter_text, instructions_markdown = self._split_frontmatter(raw_text, path)
        try:
            metadata = SkillMetadata.model_validate(tomllib.loads(frontmatter_text))
        except (tomllib.TOMLDecodeError, ValidationError) as exc:
            msg = f"skill asset metadata is invalid: {path}"
            raise SkillLoadError(msg) from exc

        if path.parent.name != metadata.name:
            msg = (
                f"skill directory name '{path.parent.name}' does not match metadata name "
                f"'{metadata.name}'"
            )
            raise SkillLoadError(msg)

        return SkillAsset(
            metadata=metadata,
            path=path,
            instructions_markdown=instructions_markdown,
        )

    def load_all(self) -> tuple[SkillAsset, ...]:
        return tuple(self.load(skill_name) for skill_name in self.discover())

    def _split_frontmatter(self, raw_text: str, path: Path) -> tuple[str, str]:
        lines = raw_text.splitlines()
        if len(lines) < 3 or lines[0].strip() != _FRONTMATTER_DELIMITER:
            msg = f"skill asset missing TOML frontmatter: {path}"
            raise SkillLoadError(msg)

        try:
            closing_index = next(
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.strip() == _FRONTMATTER_DELIMITER
            )
        except StopIteration as exc:
            msg = f"skill asset missing closing frontmatter delimiter: {path}"
            raise SkillLoadError(msg) from exc

        frontmatter = "\n".join(lines[1:closing_index]).strip()
        instructions_markdown = "\n".join(lines[closing_index + 1 :]).strip()

        if not frontmatter:
            msg = f"skill asset frontmatter is empty: {path}"
            raise SkillLoadError(msg)
        if not instructions_markdown:
            msg = f"skill asset body is empty: {path}"
            raise SkillLoadError(msg)

        return frontmatter, instructions_markdown
