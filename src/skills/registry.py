"""In-memory registry for loaded skill assets."""

from __future__ import annotations

from dataclasses import dataclass, field

from skills.models import SkillAsset


@dataclass(slots=True)
class SkillRegistry:
    """Stores discovered skill assets keyed by skill name."""

    _skills: dict[str, SkillAsset] = field(default_factory=dict)

    def register(self, skill: SkillAsset) -> None:
        skill_name = skill.metadata.name
        if skill_name in self._skills:
            msg = f"skill already registered: {skill_name}"
            raise ValueError(msg)
        self._skills[skill_name] = skill

    def get(self, name: str) -> SkillAsset | None:
        return self._skills.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))
