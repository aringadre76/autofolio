from __future__ import annotations

import re
from pathlib import Path

import pytest

from autofolio.config import ProfileReadmeHint, ProjectConfig
from autofolio.profile import (
    build_profile_patch,
    build_skills_patch,
    compute_insertion_line,
    construct_entry_from_template,
    create_minimal_readme,
    detect_badge_style,
    detect_duplicate,
    detect_entry_format,
    detect_project_section,
    detect_skills_section,
    extract_sample_entry,
    find_entry_positions,
    find_missing_tech_badges,
    generate_skill_badges,
    parse_profile_readme,
    validate_profile_entry,
    _split_into_sections,
)


@pytest.fixture
def sample_project() -> ProjectConfig:
    return ProjectConfig(
        title="Smart Thermostat AI",
        description="ML-powered thermostat optimization system",
        repo_url="https://github.com/arin/smart-thermostat",
        demo_url="https://thermostat.demo.com",
        tech_stack=["Python", "React"],
        tags=["machine-learning", "iot"],
    )


TABLE_README = """\
# Hello

## Projects

| Project | Description | Tech |
|---------|-------------|------|
| [Alpha](https://github.com/u/alpha) | A cool thing | Python |
| [Beta](https://github.com/u/beta) | Another thing | Rust |

## Contact

Email me.
"""

BULLET_README = """\
# Hi

## Featured Projects

- **Alpha** - A cool thing [Repo](https://github.com/u/alpha)
- **Beta** - Another cool thing [Repo](https://github.com/u/beta)
- **Gamma** - Third project [Repo](https://github.com/u/gamma)

## About

Something.
"""

BADGE_README = """\
# Hey

## Projects

[![Alpha](https://img.shields.io/badge/Alpha-blue?style=flat)](https://github.com/u/alpha)
[![Beta](https://img.shields.io/badge/Beta-green?style=flat)](https://github.com/u/beta)

## Skills

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Rust](https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white)
"""

HTML_CARD_README = """\
# Portfolio

## Projects

<a href="https://github.com/u/alpha"><img src="card1.png" alt="Alpha"></a>
<a href="https://github.com/u/beta"><img src="card2.png" alt="Beta"></a>

## Contact

Reach out.
"""

HEADING_BLOCK_README = """\
# Portfolio

## Projects

### Alpha

A cool ML project for optimizing things.

[Repo](https://github.com/u/alpha)

### Beta

A web app for tracking stuff.

[Repo](https://github.com/u/beta)

## About

I build things.
"""

PLAIN_README = """\
# Hello

## Projects

I built Alpha, which does something cool. Check it out at https://github.com/u/alpha.

I also made Beta for tracking tasks.

## Bio

Software dev.
"""

EMPTY_README = ""

NO_PROJECTS_README = """\
# Hello

## About

I'm a developer.

## Contact

Email me.
"""

SKILLS_README = """\
# Hello

## Skills

![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat&logo=javascript&logoColor=black)

## Projects

- **Alpha** - A cool thing [Repo](https://github.com/u/alpha)
- **Beta** - Another thing [Repo](https://github.com/u/beta)
"""


class TestSplitIntoSections:
    def test_splits_by_headings(self) -> None:
        sections = _split_into_sections(TABLE_README)
        headings = [s[0] for s in sections]
        assert "## Projects" in headings
        assert "## Contact" in headings

    def test_empty_content(self) -> None:
        sections = _split_into_sections("")
        assert sections == []

    def test_no_headings(self) -> None:
        sections = _split_into_sections("just some text\nand more text")
        assert len(sections) == 1
        assert sections[0][0] == ""


class TestDetectProjectSection:
    def test_finds_projects_heading(self) -> None:
        sections = _split_into_sections(TABLE_README)
        result = detect_project_section(sections)
        assert result is not None
        heading, start, end, text = result
        assert "Project" in heading

    def test_finds_featured_projects(self) -> None:
        sections = _split_into_sections(BULLET_README)
        result = detect_project_section(sections)
        assert result is not None
        assert "Featured" in result[0]

    def test_returns_none_for_no_projects(self) -> None:
        sections = _split_into_sections(NO_PROJECTS_README)
        result = detect_project_section(sections)
        assert result is None


class TestDetectEntryFormat:
    def test_table_format(self) -> None:
        sections = _split_into_sections(TABLE_README)
        proj = detect_project_section(sections)
        assert proj is not None
        fmt = detect_entry_format(proj[3])
        assert fmt == "table"

    def test_bullet_list_format(self) -> None:
        sections = _split_into_sections(BULLET_README)
        proj = detect_project_section(sections)
        assert proj is not None
        fmt = detect_entry_format(proj[3])
        assert fmt == "bullet_list"

    def test_badge_grid_format(self) -> None:
        sections = _split_into_sections(BADGE_README)
        proj = detect_project_section(sections)
        assert proj is not None
        fmt = detect_entry_format(proj[3])
        assert fmt == "badge_grid"

    def test_html_cards_format(self) -> None:
        sections = _split_into_sections(HTML_CARD_README)
        proj = detect_project_section(sections)
        assert proj is not None
        fmt = detect_entry_format(proj[3])
        assert fmt == "html_cards"

    def test_heading_blocks_format(self) -> None:
        sections = _split_into_sections(HEADING_BLOCK_README)
        proj = detect_project_section(sections)
        assert proj is not None
        fmt = detect_entry_format(proj[3])
        assert fmt == "heading_blocks"

    def test_plain_format(self) -> None:
        sections = _split_into_sections(PLAIN_README)
        proj = detect_project_section(sections)
        assert proj is not None
        fmt = detect_entry_format(proj[3])
        assert fmt == "plain"

    def test_empty_section(self) -> None:
        assert detect_entry_format("") == "plain"


class TestExtractSampleEntry:
    def test_table_sample(self) -> None:
        sample = extract_sample_entry(
            "| A | B |\n|---|---|\n| x | y |\n| p | q |",
            "table",
        )
        assert "p" in sample and "q" in sample

    def test_bullet_sample(self) -> None:
        text = "- **First** - desc1\n- **Second** - desc2"
        sample = extract_sample_entry(text, "bullet_list")
        assert "Second" in sample

    def test_badge_sample(self) -> None:
        text = "[![A](https://img.shields.io/badge/A-blue)](url1)\n[![B](https://img.shields.io/badge/B-red)](url2)"
        sample = extract_sample_entry(text, "badge_grid")
        assert "B" in sample

    def test_heading_block_sample(self) -> None:
        text = "### Alpha\n\nDescription A\n\n### Beta\n\nDescription B"
        sample = extract_sample_entry(text, "heading_blocks")
        assert "Beta" in sample

    def test_empty_section(self) -> None:
        assert extract_sample_entry("", "table") == ""


class TestFindEntryPositions:
    def test_table_positions(self) -> None:
        text = "\n| A | B |\n|---|---|\n| x | y |\n| p | q |"
        positions = find_entry_positions(text, "table", 10)
        assert len(positions) == 2
        assert positions[0] == 14
        assert positions[1] == 15

    def test_bullet_positions(self) -> None:
        text = "\n- **A** - desc\n- **B** - desc\n- **C** - desc"
        positions = find_entry_positions(text, "bullet_list", 5)
        assert len(positions) == 3
        assert positions[0] == 7

    def test_badge_positions(self) -> None:
        text = (
            "\n[![A](https://img.shields.io/badge/A-blue)](u)\n"
            "[![B](https://img.shields.io/badge/B-red)](u)"
        )
        positions = find_entry_positions(text, "badge_grid", 1)
        assert len(positions) == 2
        assert positions[0] == 3

    def test_empty_section(self) -> None:
        assert find_entry_positions("", "table", 1) == []


class TestComputeInsertionLine:
    def _make_hint(self, positions: list[int]) -> ProfileReadmeHint:
        return ProfileReadmeHint(
            section_heading="## Projects",
            section_start_line=5,
            section_end_line=20,
            format="bullet_list",
            sample_entry="- **A** - desc",
            entry_positions=positions,
        )

    def test_top_priority(self) -> None:
        hint = self._make_hint([8, 10, 12])
        assert compute_insertion_line(hint, "top") == 8

    def test_middle_priority(self) -> None:
        hint = self._make_hint([8, 10, 12, 14])
        assert compute_insertion_line(hint, "middle") == 12

    def test_bottom_priority(self) -> None:
        hint = self._make_hint([8, 10, 12])
        assert compute_insertion_line(hint, "bottom") == 21

    def test_empty_positions_returns_section_end(self) -> None:
        hint = self._make_hint([])
        assert compute_insertion_line(hint, "top") == 21


class TestValidateProfileEntry:
    def _make_table_hint(self) -> ProfileReadmeHint:
        return ProfileReadmeHint(
            section_heading="## Projects",
            section_start_line=3,
            section_end_line=10,
            format="table",
            sample_entry="| [Alpha](url) | A cool thing | Python |",
            entry_positions=[5, 6],
        )

    def _make_html_hint(self) -> ProfileReadmeHint:
        return ProfileReadmeHint(
            section_heading="## Projects",
            section_start_line=3,
            section_end_line=10,
            format="html_cards",
            sample_entry='<a href="url"><img src="img.png" alt="A"></a>',
            entry_positions=[5],
        )

    def _make_badge_hint(self) -> ProfileReadmeHint:
        return ProfileReadmeHint(
            section_heading="## Projects",
            section_start_line=3,
            section_end_line=10,
            format="badge_grid",
            sample_entry="[![A](https://img.shields.io/badge/A-blue)](url)",
            entry_positions=[5],
        )

    def test_empty_entry_fails(self) -> None:
        hint = self._make_table_hint()
        assert validate_profile_entry("", hint) is False

    def test_triple_backtick_fails(self) -> None:
        hint = self._make_table_hint()
        assert validate_profile_entry("```\n| a | b | c |\n```", hint) is False

    def test_preamble_artifact_fails(self) -> None:
        hint = self._make_table_hint()
        assert validate_profile_entry("Here is the entry:\n| a | b | c |", hint) is False
        assert validate_profile_entry("Sure, here you go", hint) is False

    def test_table_column_mismatch_fails(self) -> None:
        hint = self._make_table_hint()
        assert validate_profile_entry("| a | b |", hint) is False

    def test_valid_table_entry_passes(self) -> None:
        hint = self._make_table_hint()
        assert validate_profile_entry("| [New](url) | desc | Tech |", hint) is True

    def test_html_unbalanced_tags_fail(self) -> None:
        hint = self._make_html_hint()
        assert validate_profile_entry('<a href="url"><img src="img.png">', hint) is False

    def test_valid_html_entry_passes(self) -> None:
        hint = self._make_html_hint()
        assert validate_profile_entry(
            '<a href="url"><img src="img.png" alt="X"></a>', hint
        ) is True

    def test_badge_missing_image_syntax_fails(self) -> None:
        hint = self._make_badge_hint()
        assert validate_profile_entry("just text", hint) is False

    def test_valid_badge_entry_passes(self) -> None:
        hint = self._make_badge_hint()
        assert validate_profile_entry(
            "[![New](https://img.shields.io/badge/New-red)](url)", hint
        ) is True

    def test_bullet_list_passes(self) -> None:
        hint = ProfileReadmeHint(
            section_heading="## Projects",
            section_start_line=3,
            section_end_line=10,
            format="bullet_list",
            sample_entry="- **A** - desc",
            entry_positions=[5],
        )
        assert validate_profile_entry("- **B** - new desc", hint) is True


class TestConstructEntryFromTemplate:
    def test_table_entry(self, sample_project: ProjectConfig) -> None:
        sample = "| [Alpha](https://github.com/u/alpha) | A thing | Python |"
        entry = construct_entry_from_template(sample_project, sample, "table")
        assert "|" in entry
        assert sample_project.title in entry
        assert entry.count("|") == sample.count("|")

    def test_bullet_entry(self, sample_project: ProjectConfig) -> None:
        sample = "- **Alpha** - A cool thing [Repo](https://github.com/u/alpha)"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert entry.startswith("-")
        assert sample_project.title in entry

    def test_badge_entry(self, sample_project: ProjectConfig) -> None:
        entry = construct_entry_from_template(sample_project, "", "badge_grid")
        assert "![" in entry
        assert "img.shields.io" in entry
        assert sample_project.title in entry

    def test_heading_block_entry(self, sample_project: ProjectConfig) -> None:
        sample = "#### Some Project\nDescription\n- **Tech Stack:** Python\n- [View Project](url)"
        entry = construct_entry_from_template(sample_project, sample, "heading_blocks")
        assert entry.startswith("#### ")
        assert sample_project.title in entry
        assert sample_project.repo_url in entry
        assert "Tech Stack" in entry

    def test_plain_entry(self, sample_project: ProjectConfig) -> None:
        entry = construct_entry_from_template(sample_project, "", "plain")
        assert sample_project.title in entry
        assert sample_project.description in entry

    def test_html_card_entry(self, sample_project: ProjectConfig) -> None:
        sample = '<a href="https://github.com/u/alpha"><img src="card.png" alt="Alpha">Old Title</a>'
        entry = construct_entry_from_template(sample_project, sample, "html_cards")
        assert sample_project.repo_url in entry


class TestDetectDuplicate:
    def test_matches_repo_url(self) -> None:
        content = "- **Alpha** - desc [Repo](https://github.com/arin/smart-thermostat)"
        project = ProjectConfig(
            title="Smart Thermostat AI",
            description="desc",
            repo_url="https://github.com/arin/smart-thermostat",
        )
        assert detect_duplicate(content, project) is True

    def test_matches_title_bold(self) -> None:
        content = "- **Smart Thermostat AI** - some desc"
        project = ProjectConfig(
            title="Smart Thermostat AI",
            description="desc",
            repo_url="https://github.com/arin/other",
        )
        assert detect_duplicate(content, project) is True

    def test_no_duplicate(self) -> None:
        content = "- **Alpha** - desc"
        project = ProjectConfig(
            title="Smart Thermostat AI",
            description="desc",
            repo_url="https://github.com/arin/smart-thermostat",
        )
        assert detect_duplicate(content, project) is False

    def test_title_match_case_insensitive(self) -> None:
        content = "### smart thermostat ai\n\nSome desc"
        project = ProjectConfig(
            title="Smart Thermostat AI",
            description="desc",
            repo_url="https://github.com/arin/other",
        )
        assert detect_duplicate(content, project) is True


class TestParseProfileReadme:
    def test_table_readme(self) -> None:
        hint = parse_profile_readme(TABLE_README)
        assert hint is not None
        assert hint.format == "table"
        assert len(hint.entry_positions) == 2

    def test_bullet_readme(self) -> None:
        hint = parse_profile_readme(BULLET_README)
        assert hint is not None
        assert hint.format == "bullet_list"
        assert len(hint.entry_positions) == 3

    def test_badge_readme(self) -> None:
        hint = parse_profile_readme(BADGE_README)
        assert hint is not None
        assert hint.format == "badge_grid"
        assert len(hint.entry_positions) == 2

    def test_heading_block_readme(self) -> None:
        hint = parse_profile_readme(HEADING_BLOCK_README)
        assert hint is not None
        assert hint.format == "heading_blocks"
        assert len(hint.entry_positions) == 2

    def test_empty_readme_returns_none(self) -> None:
        assert parse_profile_readme("") is None
        assert parse_profile_readme("   ") is None

    def test_no_project_section_returns_none(self) -> None:
        assert parse_profile_readme(NO_PROJECTS_README) is None


class TestDetectSkillsSection:
    def test_finds_skills_section(self) -> None:
        result = detect_skills_section(SKILLS_README)
        assert result is not None
        start, end, text = result
        assert "Python" in text
        assert "JavaScript" in text

    def test_no_skills_section(self) -> None:
        assert detect_skills_section(TABLE_README) is None

    def test_skills_in_badge_readme(self) -> None:
        result = detect_skills_section(BADGE_README)
        assert result is not None
        _, _, text = result
        assert "Python" in text
        assert "Rust" in text


class TestFindMissingTechBadges:
    def test_finds_missing(self) -> None:
        skills_text = "![Python](badge) ![JavaScript](badge)"
        missing = find_missing_tech_badges(skills_text, ["Python", "React", "Docker"])
        assert "React" in missing
        assert "Docker" in missing
        assert "Python" not in missing

    def test_all_present(self) -> None:
        skills_text = "![Python](badge) ![React](badge)"
        missing = find_missing_tech_badges(skills_text, ["Python", "React"])
        assert missing == []

    def test_case_insensitive(self) -> None:
        skills_text = "![python](badge)"
        missing = find_missing_tech_badges(skills_text, ["Python"])
        assert missing == []


class TestDetectBadgeStyle:
    def test_detects_flat(self) -> None:
        text = "![X](https://img.shields.io/badge/X-blue?style=flat)"
        assert detect_badge_style(text) == "flat"

    def test_detects_for_the_badge(self) -> None:
        text = "![X](https://img.shields.io/badge/X-blue?style=for-the-badge)"
        assert detect_badge_style(text) == "for-the-badge"

    def test_default_flat(self) -> None:
        assert detect_badge_style("no badges here") == "flat"


class TestGenerateSkillBadges:
    def test_generates_badges(self) -> None:
        badges = generate_skill_badges(["Python", "React"], "flat")
        assert len(badges) == 2
        assert all("img.shields.io" in b for b in badges)
        assert all("style=flat" in b for b in badges)

    def test_uses_correct_style(self) -> None:
        badges = generate_skill_badges(["Python"], "for-the-badge")
        assert "style=for-the-badge" in badges[0]


class TestBuildProfilePatch:
    def _make_hint(self) -> ProfileReadmeHint:
        return ProfileReadmeHint(
            section_heading="## Projects",
            section_start_line=5,
            section_end_line=15,
            format="bullet_list",
            sample_entry="- **A** - desc",
            entry_positions=[7, 9, 11],
        )

    def test_top_priority_patch(self) -> None:
        hint = self._make_hint()
        patch = build_profile_patch("content", "- **New** - desc", hint, "top")
        assert patch.action == "insert_before_line"
        assert patch.target_line == 7

    def test_bottom_priority_patch(self) -> None:
        hint = self._make_hint()
        patch = build_profile_patch("content", "- **New** - desc", hint, "bottom")
        assert patch.target_line == 16

    def test_middle_priority_patch(self) -> None:
        hint = self._make_hint()
        patch = build_profile_patch("content", "- **New** - desc", hint, "middle")
        assert patch.target_line == 9


class TestBuildSkillsPatch:
    def test_returns_patch_for_missing_tech(self, sample_project: ProjectConfig) -> None:
        patch = build_skills_patch(SKILLS_README, sample_project)
        assert patch is not None
        assert "React" in patch.content

    def test_returns_none_when_no_skills_section(self, sample_project: ProjectConfig) -> None:
        patch = build_skills_patch(TABLE_README, sample_project)
        assert patch is None

    def test_returns_none_when_all_tech_present(self) -> None:
        project = ProjectConfig(
            title="Test",
            description="desc",
            repo_url="https://github.com/u/test",
            tech_stack=["Python", "JavaScript"],
        )
        patch = build_skills_patch(SKILLS_README, project)
        assert patch is None


class TestCreateMinimalReadme:
    def test_contains_username(self) -> None:
        readme = create_minimal_readme("testuser")
        assert "testuser" in readme
        assert "## Projects" in readme


NUMBERED_LIST_README = """\
# Hi

## Projects

1. **Alpha** - A cool thing [Repo](https://github.com/u/alpha)
2. **Beta** - Another cool thing [Repo](https://github.com/u/beta)
3. **Gamma** - Third project [Repo](https://github.com/u/gamma)

## About

Something.
"""

LINK_ONLY_BULLET_README = """\
# Hi

## Projects

- [Alpha](https://github.com/u/alpha)
- [Beta](https://github.com/u/beta)
- [Gamma](https://github.com/u/gamma)

## About

Something.
"""

LINKED_NAME_BULLET_README = """\
# Hi

## Projects

- [Alpha](https://github.com/u/alpha) - A cool thing
- [Beta](https://github.com/u/beta) - Another cool thing

## About

Something.
"""

BOLD_LINKED_BULLET_README = """\
# Hi

## Projects

- **[Alpha](https://github.com/u/alpha)** - A cool ML thing
- **[Beta](https://github.com/u/beta)** - A web app

## About

Something.
"""

COLON_BULLET_README = """\
# Hello

## Projects

- **Alpha**: A cool ML project
- **Beta**: A web app for tracking things

## Contact

Email me.
"""

ASTERISK_BULLET_README = """\
# Hello

## Featured Work

* **Alpha** - A cool ML project [Repo](https://github.com/u/alpha)
* **Beta** - A web app [Repo](https://github.com/u/beta)

## Contact

Email me.
"""

SINGLE_BULLET_README = """\
# Hello

## Projects

- **Alpha** - My only project so far [Repo](https://github.com/u/alpha)

## About

I'm a developer.
"""

SINGLE_HEADING_BLOCK_README = """\
# Hello

## Projects

### Alpha

A cool ML project for optimizing things.

[Repo](https://github.com/u/alpha)

## About

I build things.
"""

SINGLE_TABLE_README = """\
# Hello

## Projects

| Project | Description |
|---------|-------------|
| [Alpha](https://github.com/u/alpha) | A cool thing |

## Contact

Email me.
"""

TWO_COL_TABLE_README = """\
# Hello

## Projects

| Project | Description |
|---------|-------------|
| [Alpha](https://github.com/u/alpha) | A cool thing |
| [Beta](https://github.com/u/beta) | Another thing |

## Contact

Email me.
"""

BARE_LINK_README = """\
# Hello

## Projects

[Alpha](https://github.com/u/alpha)
[Beta](https://github.com/u/beta)
[Gamma](https://github.com/u/gamma)

## About

Something.
"""

DETAILS_README = """\
# Hello

## Projects

<details>
<summary>Alpha</summary>
A cool ML project.
<a href="https://github.com/u/alpha">View</a>
</details>
<details>
<summary>Beta</summary>
A web app.
<a href="https://github.com/u/beta">View</a>
</details>

## About

Something.
"""

HASH3_SECTIONS_README = """\
# Hi

### Projects

- **Alpha** - A cool thing [Repo](https://github.com/u/alpha)
- **Beta** - Another thing [Repo](https://github.com/u/beta)

### About

I'm a developer.
"""

HTML_COMMENT_README = """\
# Hi

<!-- PROJECTS:START -->
- **Alpha** - A cool thing [Repo](https://github.com/u/alpha)
- **Beta** - Another thing [Repo](https://github.com/u/beta)
<!-- PROJECTS:END -->

## About

I'm a developer.
"""

NO_DESC_BULLET_README = """\
# Hello

## Projects

- **Alpha** [Repo](https://github.com/u/alpha)
- **Beta** [Repo](https://github.com/u/beta)

## About

Something.
"""

PLAIN_BARE_URL_README = """\
# Hello

## Projects

I built Alpha, which does something cool. Check it out at https://github.com/u/alpha.

I also made Beta for tracking tasks at https://github.com/u/beta.

## Bio

Software dev.
"""

BOLD_NO_LINK_README = """\
# Hello

## Projects

- **Alpha** - A cool ML project
- **Beta** - A web app for tracking things

## About

Something.
"""

HEADING_BLOCK_NO_LINKS_README = """\
# Portfolio

## Projects

### Alpha

A cool ML project for optimizing things.

### Beta

A web app for tracking stuff.

## About

I build things.
"""

HEADING_BLOCK_BULLET_FIELDS_README = """\
# Portfolio

## Projects

#### Alpha

A cool ML project.

- **Tech Stack:** Python, TensorFlow
- **Tags:** machine-learning, iot
- [View Project](https://github.com/u/alpha)

#### Beta

A web app.

- **Tech Stack:** React, Node.js
- **Tags:** web, fullstack
- [View Project](https://github.com/u/beta)

## About

I build things.
"""


class TestNumberedListFormat:
    def test_detected_as_bullet_list(self) -> None:
        hint = parse_profile_readme(NUMBERED_LIST_README)
        assert hint is not None
        assert hint.format == "bullet_list"

    def test_entry_positions_found(self) -> None:
        hint = parse_profile_readme(NUMBERED_LIST_README)
        assert hint is not None
        assert len(hint.entry_positions) == 3

    def test_sample_extracted(self) -> None:
        hint = parse_profile_readme(NUMBERED_LIST_README)
        assert hint is not None
        assert "Gamma" in hint.sample_entry

    def test_construct_entry_uses_numbered_prefix(self, sample_project: ProjectConfig) -> None:
        sample = "1. **Alpha** - A cool thing [Repo](https://github.com/u/alpha)"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert sample_project.title in entry
        assert re.match(r"^\d+[.)]\s+", entry)


class TestLinkOnlyBulletFormat:
    def test_detected_as_bullet_list(self) -> None:
        hint = parse_profile_readme(LINK_ONLY_BULLET_README)
        assert hint is not None
        assert hint.format == "bullet_list"

    def test_construct_link_only_entry(self, sample_project: ProjectConfig) -> None:
        sample = "- [Alpha](https://github.com/u/alpha)"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert sample_project.title in entry
        assert sample_project.repo_url in entry
        assert "**" not in entry

    def test_entry_positions(self) -> None:
        hint = parse_profile_readme(LINK_ONLY_BULLET_README)
        assert hint is not None
        assert len(hint.entry_positions) == 3


class TestLinkedNameBulletFormat:
    def test_detected_as_bullet_list(self) -> None:
        hint = parse_profile_readme(LINKED_NAME_BULLET_README)
        assert hint is not None
        assert hint.format == "bullet_list"

    def test_construct_linked_name_entry(self, sample_project: ProjectConfig) -> None:
        sample = "- [Alpha](https://github.com/u/alpha) - A cool thing"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert entry.startswith("- [")
        assert sample_project.title in entry
        assert sample_project.repo_url in entry
        assert sample_project.description in entry


class TestBoldLinkedBulletFormat:
    def test_detected_as_bullet_list(self) -> None:
        hint = parse_profile_readme(BOLD_LINKED_BULLET_README)
        assert hint is not None
        assert hint.format == "bullet_list"

    def test_construct_bold_linked_entry(self, sample_project: ProjectConfig) -> None:
        sample = "- **[Alpha](https://github.com/u/alpha)** - A cool ML thing"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert f"**[{sample_project.title}]({sample_project.repo_url})**" in entry
        assert sample_project.description in entry


class TestColonSeparatorBulletFormat:
    def test_construct_colon_entry(self, sample_project: ProjectConfig) -> None:
        sample = "- **Alpha**: A cool ML project"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert f"**{sample_project.title}**" in entry
        assert ": " in entry
        assert sample_project.description in entry

    def test_no_trailing_link_when_sample_has_none(self, sample_project: ProjectConfig) -> None:
        sample = "- **Alpha**: A cool ML project"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert "[Repo]" not in entry


class TestAsteriskBulletFormat:
    def test_detected_as_bullet_list(self) -> None:
        hint = parse_profile_readme(ASTERISK_BULLET_README)
        assert hint is not None
        assert hint.format == "bullet_list"

    def test_construct_asterisk_entry(self, sample_project: ProjectConfig) -> None:
        sample = "* **Alpha** - A cool ML project [Repo](https://github.com/u/alpha)"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert entry.startswith("* ")
        assert sample_project.title in entry


class TestSingleProjectEntries:
    def test_single_bullet(self) -> None:
        hint = parse_profile_readme(SINGLE_BULLET_README)
        assert hint is not None
        assert hint.format == "bullet_list"
        assert len(hint.entry_positions) == 1

    def test_single_heading_block(self) -> None:
        hint = parse_profile_readme(SINGLE_HEADING_BLOCK_README)
        assert hint is not None
        assert hint.format == "heading_blocks"
        assert len(hint.entry_positions) == 1

    def test_single_table_row(self) -> None:
        hint = parse_profile_readme(SINGLE_TABLE_README)
        assert hint is not None
        assert hint.format == "table"
        assert len(hint.entry_positions) == 1


class TestTwoColumnTable:
    def test_detected_as_table(self) -> None:
        hint = parse_profile_readme(TWO_COL_TABLE_README)
        assert hint is not None
        assert hint.format == "table"

    def test_construct_two_col_entry(self, sample_project: ProjectConfig) -> None:
        sample = "| [Alpha](https://github.com/u/alpha) | A cool thing |"
        entry = construct_entry_from_template(sample_project, sample, "table")
        assert entry.count("|") == sample.count("|")
        assert sample_project.title in entry
        assert sample_project.description in entry


class TestBareLinkFormat:
    def test_detected_as_bullet_list(self) -> None:
        hint = parse_profile_readme(BARE_LINK_README)
        assert hint is not None
        assert hint.format == "bullet_list"

    def test_entry_positions(self) -> None:
        hint = parse_profile_readme(BARE_LINK_README)
        assert hint is not None
        assert len(hint.entry_positions) == 3


class TestDetailsAccordionFormat:
    def test_detected_as_html_cards(self) -> None:
        hint = parse_profile_readme(DETAILS_README)
        assert hint is not None
        assert hint.format == "html_cards"

    def test_sample_extracted(self) -> None:
        hint = parse_profile_readme(DETAILS_README)
        assert hint is not None
        assert "<details>" in hint.sample_entry.lower()
        assert "<summary>" in hint.sample_entry.lower()

    def test_construct_details_entry(self, sample_project: ProjectConfig) -> None:
        sample = (
            "<details>\n<summary>Alpha</summary>\n"
            "A cool ML project.\n"
            '<a href="https://github.com/u/alpha">View</a>\n'
            "</details>"
        )
        entry = construct_entry_from_template(sample_project, sample, "html_cards")
        assert sample_project.title in entry
        assert sample_project.repo_url in entry
        assert "<details>" in entry
        assert "</details>" in entry


class TestHash3Sections:
    def test_splits_on_hash3_when_no_hash2(self) -> None:
        hint = parse_profile_readme(HASH3_SECTIONS_README)
        assert hint is not None
        assert hint.format == "bullet_list"
        assert len(hint.entry_positions) == 2

    def test_section_heading_detected(self) -> None:
        sections = _split_into_sections(HASH3_SECTIONS_README)
        headings = [s[0] for s in sections]
        assert any("Projects" in h for h in headings)
        assert any("About" in h for h in headings)


class TestHTMLCommentMarkers:
    def test_section_detected(self) -> None:
        hint = parse_profile_readme(HTML_COMMENT_README)
        assert hint is not None
        assert hint.format == "bullet_list"
        assert len(hint.entry_positions) == 2


class TestNoDescBullet:
    def test_detected_as_bullet_list(self) -> None:
        hint = parse_profile_readme(NO_DESC_BULLET_README)
        assert hint is not None
        assert hint.format == "bullet_list"

    def test_construct_no_desc_entry(self, sample_project: ProjectConfig) -> None:
        sample = "- **Alpha** [Repo](https://github.com/u/alpha)"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert f"**{sample_project.title}**" in entry
        assert sample_project.repo_url in entry


class TestBoldNoLinkBullet:
    def test_construct_bold_no_link_entry(self, sample_project: ProjectConfig) -> None:
        sample = "- **Alpha** - A cool ML project"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert entry.startswith("- **")
        assert sample_project.description in entry
        assert "[Repo]" not in entry

    def test_full_readme_parse(self) -> None:
        hint = parse_profile_readme(BOLD_NO_LINK_README)
        assert hint is not None
        assert hint.format == "bullet_list"
        assert len(hint.entry_positions) == 2


class TestPlainBareURLFormat:
    def test_detected_as_plain(self) -> None:
        hint = parse_profile_readme(PLAIN_BARE_URL_README)
        assert hint is not None
        assert hint.format == "plain"

    def test_construct_plain_entry_bare_url(self, sample_project: ProjectConfig) -> None:
        sample = "I built Alpha, which does something cool. Check it out at https://github.com/u/alpha."
        entry = construct_entry_from_template(sample_project, sample, "plain")
        assert sample_project.title in entry
        assert sample_project.description in entry


class TestHeadingBlockNoLinks:
    def test_detected_as_heading_blocks(self) -> None:
        hint = parse_profile_readme(HEADING_BLOCK_NO_LINKS_README)
        assert hint is not None
        assert hint.format == "heading_blocks"

    def test_construct_heading_no_links(self, sample_project: ProjectConfig) -> None:
        sample = "### Alpha\n\nA cool ML project for optimizing things."
        entry = construct_entry_from_template(sample_project, sample, "heading_blocks")
        assert f"### {sample_project.title}" in entry
        assert sample_project.description in entry


class TestHeadingBlockBulletFields:
    def test_detected_as_heading_blocks(self) -> None:
        hint = parse_profile_readme(HEADING_BLOCK_BULLET_FIELDS_README)
        assert hint is not None
        assert hint.format == "heading_blocks"
        assert len(hint.entry_positions) == 2

    def test_construct_entry_with_bullet_fields(self, sample_project: ProjectConfig) -> None:
        sample = (
            "#### Alpha\n\nA cool ML project.\n\n"
            "- **Tech Stack:** Python, TensorFlow\n"
            "- **Tags:** machine-learning, iot\n"
            "- [View Project](https://github.com/u/alpha)"
        )
        entry = construct_entry_from_template(sample_project, sample, "heading_blocks")
        assert entry.startswith("#### ")
        assert sample_project.title in entry
        assert "Tech Stack" in entry
        assert sample_project.repo_url in entry


class TestEdgeCaseFormats:
    def test_single_badge_entry(self) -> None:
        readme = (
            "# Hi\n\n## Projects\n\n"
            "[![Alpha](https://img.shields.io/badge/Alpha-blue?style=flat)]"
            "(https://github.com/u/alpha)\n\n## About\n\nDev.\n"
        )
        hint = parse_profile_readme(readme)
        assert hint is not None
        assert hint.format == "badge_grid"

    def test_single_html_card(self) -> None:
        readme = (
            "# Hi\n\n## Projects\n\n"
            '<a href="https://github.com/u/alpha"><img src="card.png" alt="Alpha"></a>\n\n'
            "## About\n\nDev.\n"
        )
        hint = parse_profile_readme(readme)
        assert hint is not None
        assert hint.format == "html_cards"

    def test_readme_with_only_hash1_and_content(self) -> None:
        readme = "# My Portfolio\n\nI built **Alpha** - A cool thing https://github.com/u/alpha\n"
        hint = parse_profile_readme(readme)
        assert hint is None or hint.format == "plain"

    def test_indented_bullets(self) -> None:
        section_text = "  - **Alpha** - thing\n  - **Beta** - thing"
        fmt = detect_entry_format(section_text)
        assert fmt == "bullet_list"

    def test_construct_entry_preserves_indent(self, sample_project: ProjectConfig) -> None:
        sample = "  - **Alpha** - A cool thing"
        entry = construct_entry_from_template(sample_project, sample, "bullet_list")
        assert entry.startswith("  - ")

    def test_mixed_content_picks_dominant_format(self) -> None:
        section_text = (
            "- **Alpha** - thing [Repo](https://github.com/u/alpha)\n"
            "- **Beta** - thing [Repo](https://github.com/u/beta)\n"
            "- **Gamma** - thing [Repo](https://github.com/u/gamma)\n"
            "| X | Y |\n"
        )
        fmt = detect_entry_format(section_text)
        assert fmt == "bullet_list"

    def test_html_table_layout(self) -> None:
        section_text = (
            '<a href="https://github.com/u/alpha">'
            '<img src="card1.png" alt="Alpha"></a>\n'
        )
        fmt = detect_entry_format(section_text)
        assert fmt == "html_cards"
