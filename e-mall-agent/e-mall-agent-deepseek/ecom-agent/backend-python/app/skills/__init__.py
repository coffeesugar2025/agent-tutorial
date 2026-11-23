"""Skill 子系统：``SKILL.md`` 渐进式披露（metadata → 正文 → 资源）。

内置技能位于 :mod:`app.skills.builtin`，可用 ``SKILLS_DIR`` 指向自定义目录覆盖。
"""

from app.skills.loader import (
    SKILL_FILE,
    Skill,
    SkillError,
    SkillLoader,
    SkillMeta,
    SkillNotFound,
    get_loader,
    list_skills,
    load_skill,
    load_skill_prompt,
    parse_frontmatter,
    reset_loader,
    skill_index,
    split_frontmatter,
)

__all__ = [
    "SKILL_FILE",
    "Skill",
    "SkillError",
    "SkillLoader",
    "SkillMeta",
    "SkillNotFound",
    "get_loader",
    "list_skills",
    "load_skill",
    "load_skill_prompt",
    "parse_frontmatter",
    "reset_loader",
    "skill_index",
    "split_frontmatter",
]
