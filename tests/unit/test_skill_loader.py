from pathlib import Path

import pytest

from skills.loader import SkillLoader, SkillLoadError


def test_skill_loader_reads_repository_skill_asset() -> None:
    root = Path(__file__).resolve().parents[2] / "skills"

    asset = SkillLoader(root).load("incident-triage")

    assert asset.metadata.name == "incident-triage"
    assert asset.metadata.expected_outputs == [
        "initial incident summary",
        "suspected blast radius",
        "recommended next read-only checks",
    ]
    assert "# Incident Triage" in asset.instructions_markdown


def test_skill_loader_rejects_missing_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "broken-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Broken Skill\n", encoding="utf-8")

    with pytest.raises(SkillLoadError):
        SkillLoader(tmp_path).load("broken-skill")
