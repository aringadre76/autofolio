from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from autofolio.config import PatchAction, ProfileReadmeHint, ProjectConfig
from autofolio.detector import DetectionResult
from autofolio.llm import invoke_with_retry

console = Console()

ProfileFormat = Literal[
    "table", "bullet_list", "badge_grid",
    "html_cards", "heading_blocks", "plain"
]

PROFILE_ENTRY_SYSTEM_PROMPT = """\
You are AutoFolio, a tool that generates entries for GitHub profile READMEs.

You will receive:
1. The detected format of the project section (table, bullet list, badges, HTML cards, etc.)
2. A sample entry from the existing profile README
3. Metadata about the new project

Your job: generate ONE entry in the EXACT same format as the sample.

CRITICAL RULES:
- Match the format character-for-character: same markdown syntax, same table columns,
  same bullet style, same badge URL pattern, same HTML tags and structure.
- Output ONLY the new entry. No explanation, no markdown fences, no preamble.
- Do not change the style, indentation, or structure of the existing format.
"""


def discover_profile_repo(
    github_username: str,
    github_token: str | None = None,
) -> bool:
    token = github_token or os.environ.get("GITHUB_TOKEN")
    if token:
        return _check_repo_api(github_username, token)
    return _check_repo_gh_cli(github_username)


def _check_repo_api(username: str, token: str) -> bool:
    try:
        from github import Github, GithubException
        g = Github(token)
        try:
            g.get_repo(f"{username}/{username}")
            return True
        except GithubException:
            return False
    except ImportError:
        return _check_repo_gh_cli(username)


def _check_repo_gh_cli(username: str) -> bool:
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{username}/{username}", "--silent"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def extract_github_username(portfolio_url: str | None, repo_path: Path | None) -> str | None:
    if portfolio_url:
        match = re.search(r"github\.com/([^/]+)", portfolio_url)
        if match:
            return match.group(1)

    if repo_path:
        from autofolio.git_ops import get_github_remote_url
        remote = get_github_remote_url(repo_path)
        if remote:
            match = re.search(r"github\.com/([^/]+)", remote)
            if match:
                return match.group(1)

    return None


def parse_profile_readme(content: str) -> ProfileReadmeHint | None:
    if not content.strip():
        return None

    sections = _split_into_sections(content)
    if not sections:
        return None

    project_section = detect_project_section(sections)
    if project_section is None:
        return None

    heading, start_line, end_line, section_text = project_section
    fmt = detect_entry_format(section_text)
    sample = extract_sample_entry(section_text, fmt)
    positions = find_entry_positions(section_text, fmt, start_line)

    return ProfileReadmeHint(
        section_heading=heading,
        section_start_line=start_line,
        section_end_line=end_line,
        format=fmt,
        sample_entry=sample,
        entry_positions=positions,
    )


def _split_into_sections(
    content: str,
) -> list[tuple[str, int, int, str]]:
    lines = content.splitlines()
    if not lines:
        return []

    has_h2 = any(
        re.match(r"^##\s+", l) and not re.match(r"^###", l) for l in lines
    )

    if has_h2:
        heading_re = re.compile(r"^#{1,2}\s+")
        exclude_re = re.compile(r"^###")
    else:
        has_h3 = any(re.match(r"^###\s+", l) for l in lines)
        if has_h3:
            heading_re = re.compile(r"^#{1,3}\s+")
            exclude_re = re.compile(r"^####")
        else:
            heading_re = re.compile(r"^#{1,2}\s+")
            exclude_re = re.compile(r"^###")

    comment_re = re.compile(
        r"^\s*<!--\s*[\w-]+\s*:\s*START\s*-->", re.IGNORECASE
    )

    sections: list[tuple[str, int, int, str]] = []
    current_heading = ""
    current_start = 1
    current_lines: list[str] = []

    for i, line in enumerate(lines, 1):
        is_heading = heading_re.match(line) and not exclude_re.match(line)
        is_marker = comment_re.match(line)
        if is_heading or is_marker:
            if current_lines or current_heading:
                sections.append((
                    current_heading,
                    current_start,
                    i - 1,
                    "\n".join(current_lines),
                ))
            current_heading = line.strip()
            current_start = i
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines or current_heading:
        sections.append((
            current_heading,
            current_start,
            len(lines),
            "\n".join(current_lines),
        ))

    return sections


PROJECT_KEYWORDS = [
    "project", "featured", "work", "built", "portfolio",
    "showcase", "highlights", "creations", "apps", "tools",
    "repos", "repositories", "open source", "side project",
    "what i", "things i",
]

PROJECT_CONTENT_SIGNALS = [
    r"github\.com/\S+",
    r"https?://\S+\.git",
    r"\*\*[^*]+\*\*\s*[-:]\s*\S",
    r"\|\s*\S+\s*\|",
    r"!\[.*?\]\(https://img\.shields\.io",
    r"<a\s+href=",
    r"###\s+\S",
    r"\d+[.)]\s+\*?\*?\[?\w",
    r"\[.+?\]\(https?://github\.com/",
    r"<details>",
    r"<summary>",
    r"repo|demo|source|code",
]


def detect_project_section(
    sections: list[tuple[str, int, int, str]],
) -> tuple[str, int, int, str] | None:
    best_score = 0.0
    best_section = None

    for heading, start, end, text in sections:
        score = _score_project_likeness(heading, text)
        if score > best_score:
            best_score = score
            best_section = (heading, start, end, text)

    threshold = 2.0
    if best_score >= threshold and best_section is not None:
        return best_section

    return None


def _score_project_likeness(heading: str, text: str) -> float:
    score = 0.0
    heading_lower = heading.lower()

    for kw in PROJECT_KEYWORDS:
        if kw in heading_lower:
            score += 3.0
            break

    combined = text.lower()
    for pattern in PROJECT_CONTENT_SIGNALS:
        matches = re.findall(pattern, combined, re.IGNORECASE)
        score += min(len(matches), 3) * 0.5

    github_urls = re.findall(r"github\.com/\S+", combined)
    score += min(len(github_urls), 5) * 0.5

    return score


def detect_entry_format(section_text: str) -> ProfileFormat:
    lines = section_text.strip().splitlines()
    if not lines:
        return "plain"

    table_rows = [l for l in lines if re.match(r"^\s*\|.*\|", l)]
    if len(table_rows) >= 2:
        return "table"

    badge_lines = [l for l in lines if "img.shields.io" in l and "![" in l]
    if len(badge_lines) >= 2:
        return "badge_grid"

    html_link_lines = [
        l for l in lines if re.search(r"<a\s+href=", l, re.IGNORECASE)
    ]
    html_img_lines = [
        l for l in lines if re.search(r"<img\s+", l, re.IGNORECASE)
    ]
    details_lines = [
        l for l in lines if re.search(r"<details>|<summary>", l, re.IGNORECASE)
    ]
    if (
        len(html_link_lines) >= 2
        or (html_link_lines and html_img_lines)
        or details_lines
    ):
        return "html_cards"

    heading_lines = [l for l in lines if re.match(r"^#{3,}\s+\S", l)]
    if heading_lines:
        return "heading_blocks"

    bullet_lines = [
        l for l in lines
        if re.match(r"^\s*[-*]\s+", l) or re.match(r"^\s*\d+[.)]\s+", l)
    ]
    if bullet_lines:
        return "bullet_list"

    if badge_lines:
        return "badge_grid"

    link_lines = [
        l for l in lines
        if re.match(r"^\s*\[.+?\]\(https?://\S+\)\s*$", l)
    ]
    if link_lines:
        return "bullet_list"

    if html_link_lines:
        return "html_cards"

    return "plain"


def extract_sample_entry(section_text: str, fmt: ProfileFormat) -> str:
    lines = section_text.strip().splitlines()
    if not lines:
        return ""

    if fmt == "table":
        data_rows = []
        for line in lines:
            if re.match(r"^\s*\|.*\|", line):
                if re.match(r"^\s*\|[\s\-:|]+\|", line):
                    continue
                data_rows.append(line)
        if len(data_rows) > 1:
            return data_rows[-1]
        if data_rows:
            return data_rows[0]
        return ""

    if fmt == "bullet_list":
        bullets = [
            l for l in lines
            if re.match(r"^\s*[-*]\s+", l) or re.match(r"^\s*\d+[.)]\s+", l)
        ]
        if not bullets:
            link_lines = [
                l for l in lines
                if re.match(r"^\s*\[.+?\]\(https?://\S+\)\s*$", l)
            ]
            if link_lines:
                return link_lines[-1]
        if bullets:
            return bullets[-1]
        return ""

    if fmt == "badge_grid":
        badge_lines = [l for l in lines if "img.shields.io" in l and "![" in l]
        if badge_lines:
            return badge_lines[-1]
        return ""

    if fmt == "html_cards":
        text = section_text.strip()
        details_blocks = _extract_details_blocks(text)
        if details_blocks:
            return details_blocks[-1]
        blocks = _extract_html_card_blocks(text)
        if blocks:
            return blocks[-1]
        return ""

    if fmt == "heading_blocks":
        entry_pattern = _get_entry_heading_pattern(lines)
        heading_indices = [
            i for i, l in enumerate(lines) if re.match(entry_pattern, l)
        ]
        if heading_indices:
            last_idx = heading_indices[-1]
            end_idx = len(lines)
            for hi in heading_indices:
                if hi > last_idx:
                    end_idx = hi
                    break
            block_lines = lines[last_idx:end_idx]
            while block_lines and not block_lines[-1].strip():
                block_lines.pop()
            return "\n".join(block_lines).strip()
        return ""

    return lines[-1] if lines else ""


def _extract_html_card_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    pattern = re.compile(r"<a\s+href=", re.IGNORECASE)
    for match in pattern.finditer(text):
        start = match.start()
        close_tag = "</a>"
        close_idx = text.find(close_tag, start)
        if close_idx >= 0:
            blocks.append(text[start:close_idx + len(close_tag)])
    return blocks


def _extract_details_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    pattern = re.compile(r"<details>", re.IGNORECASE)
    for match in pattern.finditer(text):
        start = match.start()
        close_tag = "</details>"
        close_idx = text.lower().find(close_tag.lower(), start)
        if close_idx >= 0:
            blocks.append(text[start:close_idx + len(close_tag)])
    return blocks


def find_entry_positions(
    section_text: str,
    fmt: ProfileFormat,
    section_start_line: int,
) -> list[int]:
    lines = section_text.splitlines()
    if not lines:
        return []

    positions: list[int] = []
    offset = section_start_line + 1

    if fmt == "table":
        header_skipped = False
        for i, line in enumerate(lines):
            if re.match(r"^\s*\|.*\|", line):
                if re.match(r"^\s*\|[\s\-:|]+\|", line):
                    continue
                if not header_skipped:
                    header_skipped = True
                    continue
                positions.append(offset + i)

    elif fmt == "bullet_list":
        for i, line in enumerate(lines):
            is_bullet = re.match(r"^\s*[-*]\s+", line)
            is_numbered = re.match(r"^\s*\d+[.)]\s+", line)
            is_bare_link = re.match(r"^\s*\[.+?\]\(https?://\S+\)\s*$", line)
            if is_bullet or is_numbered or is_bare_link:
                positions.append(offset + i)

    elif fmt == "badge_grid":
        for i, line in enumerate(lines):
            if "img.shields.io" in line and "![" in line:
                positions.append(offset + i)

    elif fmt == "html_cards":
        for i, line in enumerate(lines):
            if re.search(r"<a\s+href=", line, re.IGNORECASE):
                positions.append(offset + i)
            elif re.search(r"<details>", line, re.IGNORECASE):
                positions.append(offset + i)

    elif fmt == "heading_blocks":
        entry_pattern = _get_entry_heading_pattern(lines)
        for i, line in enumerate(lines):
            if re.match(entry_pattern, line):
                positions.append(offset + i)

    return positions


def _get_entry_heading_pattern(lines: list[str]) -> str:
    max_level = 0
    for line in lines:
        m = re.match(r"^(#{3,})\s+\S", line)
        if m:
            level = len(m.group(1))
            if level > max_level:
                max_level = level
    if max_level > 0:
        return rf"^{'#' * max_level}\s+\S"
    return r"^#{3,}\s+\S"


def compute_insertion_line(
    hint: ProfileReadmeHint,
    priority: str,
) -> int:
    positions = hint.entry_positions
    if not positions:
        return hint.section_end_line + 1

    if priority == "top":
        return positions[0]
    elif priority == "middle":
        mid = len(positions) // 2
        return positions[mid]
    else:
        return hint.section_end_line + 1


def generate_profile_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    hint: ProfileReadmeHint,
) -> str:
    llm_entry = _llm_generate_entry(llm, project, hint)
    if llm_entry and validate_profile_entry(llm_entry, hint):
        return llm_entry

    console.print(
        "[yellow]LLM profile entry failed validation, "
        "falling back to template construction.[/yellow]"
    )
    return construct_entry_from_template(project, hint.sample_entry, hint.format)


def _llm_generate_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    hint: ProfileReadmeHint,
) -> str | None:
    user_content = (
        f"Format: {hint.format}\n\n"
        f"Sample entry from existing profile README:\n{hint.sample_entry}\n\n"
        f"Project to add:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Generate ONE entry in the EXACT same format as the sample above.\n"
    )

    try:
        response = invoke_with_retry(
            llm,
            [
                SystemMessage(content=PROFILE_ENTRY_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ],
            step_name="Profile entry generation",
        )
        raw = response.content.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        return raw if raw else None
    except Exception as e:
        console.print(f"[yellow]LLM profile entry generation failed: {e}[/yellow]")
        return None


def validate_profile_entry(entry: str, hint: ProfileReadmeHint) -> bool:
    if not entry or not entry.strip():
        return False

    if "```" in entry:
        return False

    artifacts = [
        "here is", "here's", "sure,", "certainly",
        "i've generated", "below is", "the following",
    ]
    entry_lower = entry.lower()
    for artifact in artifacts:
        if entry_lower.startswith(artifact):
            return False

    fmt = hint.format

    if fmt == "table":
        return _validate_table_entry(entry, hint.sample_entry)
    elif fmt == "html_cards":
        return _validate_html_entry(entry)
    elif fmt == "badge_grid":
        return _validate_badge_entry(entry)

    return True


def _validate_table_entry(entry: str, sample: str) -> bool:
    entry_pipes = entry.count("|")
    sample_pipes = sample.count("|")
    if sample_pipes > 0 and entry_pipes != sample_pipes:
        return False
    if not re.match(r"^\s*\|.*\|", entry.strip()):
        return False
    return True


def _validate_html_entry(entry: str) -> bool:
    open_tags = re.findall(r"<(\w+)[\s>]", entry)
    close_tags = re.findall(r"</(\w+)>", entry)

    self_closing = {"br", "img", "hr", "input", "meta", "link"}
    filtered_open = [t.lower() for t in open_tags if t.lower() not in self_closing]
    filtered_close = [t.lower() for t in close_tags]

    from collections import Counter
    open_counts = Counter(filtered_open)
    close_counts = Counter(filtered_close)

    for tag, count in open_counts.items():
        if close_counts.get(tag, 0) < count:
            return False

    return True


def _validate_badge_entry(entry: str) -> bool:
    if "![" not in entry:
        return False
    if "](http" not in entry and "](https" not in entry:
        return False
    return True


def construct_entry_from_template(
    project: ProjectConfig,
    sample: str,
    fmt: ProfileFormat,
) -> str:
    if fmt == "table":
        return _construct_table_entry(project, sample)
    elif fmt == "bullet_list":
        return _construct_bullet_entry(project, sample)
    elif fmt == "badge_grid":
        return _construct_badge_entry(project)
    elif fmt == "html_cards":
        return _construct_html_card_entry(project, sample)
    elif fmt == "heading_blocks":
        return _construct_heading_block_entry(project, sample)
    else:
        return _construct_plain_entry(project, sample)


def _construct_table_entry(project: ProjectConfig, sample: str) -> str:
    cols = [c.strip() for c in sample.split("|") if c.strip()]
    col_count = len(cols)

    values: list[str] = []
    if col_count >= 1:
        if project.repo_url:
            values.append(f"[{project.title}]({project.repo_url})")
        else:
            values.append(project.title)
    if col_count >= 2:
        values.append(project.description)
    if col_count >= 3:
        values.append(", ".join(project.tech_stack) if project.tech_stack else "")

    while len(values) < col_count:
        values.append("")

    return "| " + " | ".join(values[:col_count]) + " |"


def _construct_bullet_entry(project: ProjectConfig, sample: str) -> str:
    prefix = "- "
    num_match = re.match(r"^(\s*)(\d+)([.)]\s+)", sample)
    dash_match = re.match(r"^(\s*)([-*])\s+", sample)
    bare_link_match = re.match(r"^\s*\[.+?\]\(https?://\S+\)\s*$", sample)

    if num_match:
        prefix = num_match.group(0)
    elif dash_match:
        prefix = dash_match.group(0)
    elif bare_link_match:
        prefix = ""

    if num_match:
        content = sample[len(num_match.group(0)):]
    elif dash_match:
        content = sample[len(dash_match.group(0)):]
    else:
        content = sample.lstrip()

    url = project.repo_url or project.demo_url or "#"

    if bare_link_match and not content.replace(sample.strip(), "").strip():
        return f"{prefix}[{project.title}]({url})"

    has_bold_link = bool(re.search(r"\*\*\[.+?\]\(.+?\)\*\*", content))
    has_bold = bool(re.search(r"\*\*[^*]+\*\*", content))
    is_link_start = bool(re.match(r"\[.+?\]\(.+?\)", content))
    is_link_only = bool(re.match(r"\[.+?\]\([^)]+\)\s*$", content))

    sep = " - "
    if re.search(r"(\*\*|(?<=\)))\s*:\s", content):
        sep = ": "
    elif re.search(r"(\*\*|(?<=\)))\s*\|\s", content):
        sep = " | "

    trailing_match = re.findall(
        r"\[([\w\s]+)\]\(https?://[^\s)]+\)\s*$", content
    )
    trailing_label = None
    if trailing_match:
        label = trailing_match[-1].strip()
        if label.lower() not in (
            project.title.lower(),
            sample.split("**")[1].lower() if "**" in sample else "",
        ):
            trailing_label = label

    has_desc = False
    if has_bold_link or has_bold:
        after_title = re.split(r"\*\*\[.+?\]\(.+?\)\*\*|\*\*[^*]+\*\*", content, 1)
        if len(after_title) > 1:
            rest = after_title[1].strip()
            rest_clean = re.sub(r"\[[\w\s]+\]\(https?://[^\s)]+\)\s*$", "", rest).strip()
            rest_clean = re.sub(r"^[-:|]\s*", "", rest_clean).strip()
            if rest_clean:
                has_desc = True
    elif is_link_start and not is_link_only:
        after_link = re.sub(r"^\[.+?\]\([^)]+\)\s*", "", content).strip()
        after_link_clean = re.sub(r"^[-:|]\s*", "", after_link).strip()
        if after_link_clean:
            has_desc = True

    if has_bold_link:
        title_part = f"**[{project.title}]({url})**"
    elif has_bold:
        title_part = f"**{project.title}**"
    elif is_link_start:
        title_part = f"[{project.title}]({url})"
    else:
        title_part = project.title

    entry = prefix + title_part

    if is_link_only:
        return entry

    if has_desc and project.description:
        entry += sep + project.description
    elif project.description and not has_bold_link and not is_link_start:
        entry += sep + project.description

    if trailing_label and project.repo_url and not has_bold_link and not is_link_start:
        entry += f" [{trailing_label}]({project.repo_url})"
    elif (
        not trailing_label
        and not has_bold_link
        and not is_link_start
        and has_bold
        and project.repo_url
        and not _sample_has_trailing_link(content)
        and _sample_has_any_url(content)
    ):
        entry += f" [{_detect_link_label(content)}]({project.repo_url})"

    return entry


def _sample_has_trailing_link(content: str) -> bool:
    return bool(re.search(r"\[[\w\s]+\]\(https?://[^\s)]+\)\s*$", content))


def _sample_has_any_url(content: str) -> bool:
    return bool(re.search(r"https?://", content))


def _detect_link_label(content: str) -> str:
    m = re.search(r"\[([\w\s]+)\]\(https?://", content)
    if m:
        return m.group(1)
    return "Repo"


def _construct_badge_entry(project: ProjectConfig) -> str:
    title_slug = project.title.replace(" ", "%20")
    badge_url = f"https://img.shields.io/badge/{title_slug}-blue?style=flat"
    link = project.repo_url or project.demo_url or "#"
    return f"[![{project.title}]({badge_url})]({link})"


def _construct_html_card_entry(project: ProjectConfig, sample: str) -> str:
    is_details = "<details>" in sample.lower()

    if is_details:
        return _construct_details_entry(project, sample)

    result = sample
    link = project.repo_url or project.demo_url or "#"

    old_urls = re.findall(r'href="([^"]*)"', result)
    if old_urls:
        result = result.replace(old_urls[0], link, 1)

    old_alt = re.findall(r'alt="([^"]*)"', result)
    if old_alt:
        result = result.replace(f'alt="{old_alt[0]}"', f'alt="{project.title}"', 1)

    old_titles = re.findall(r">([^<]{3,})<", result)
    if old_titles:
        result = result.replace(old_titles[0], project.title, 1)

    old_src = re.findall(r'src="([^"]*)"', result)
    if old_src and project.demo_url:
        result = result.replace(old_src[0], project.demo_url, 1)

    return result


def _construct_details_entry(project: ProjectConfig, sample: str) -> str:
    result = sample

    summary_match = re.search(r"<summary>(.*?)</summary>", result, re.DOTALL)
    if summary_match:
        old_summary = summary_match.group(1).strip()
        if old_summary:
            result = result.replace(old_summary, project.title, 1)

    old_urls = re.findall(r'href="([^"]*)"', result)
    if old_urls:
        link = project.repo_url or project.demo_url or "#"
        result = result.replace(old_urls[0], link, 1)

    desc_patterns = [
        (r"(<p>)(.*?)(</p>)", project.description),
        (r"(<summary>.*?</summary>\s*\n\s*)(.*?)(\n\s*(?:<|$))", project.description),
    ]
    for pattern, replacement in desc_patterns:
        m = re.search(pattern, result, re.DOTALL)
        if m and m.group(2).strip():
            result = result[:m.start(2)] + replacement + result[m.end(2):]
            break

    return result


def _construct_heading_block_entry(project: ProjectConfig, sample: str = "") -> str:
    heading_level = "###"
    heading_match = re.match(r"^(#{3,})\s+", sample)
    if heading_match:
        heading_level = heading_match.group(1)

    sample_lines = sample.strip().splitlines() if sample else []

    has_blank_after_heading = (
        len(sample_lines) >= 2 and not sample_lines[1].strip()
    )

    has_plain_desc = any(
        l.strip()
        and not re.match(r"^#{1,6}\s+", l)
        and not re.match(r"^\s*[-*]\s+", l)
        and not re.match(r"^\s*\[", l)
        for l in sample_lines[1:]
        if l.strip()
    )

    has_bullet_fields = bool(re.search(r"[-*]\s+\*\*\w+", sample))
    has_tech_field = bool(re.search(r"tech|stack|built.with", sample, re.IGNORECASE))
    has_tag_field = bool(re.search(r"tags?|categor", sample, re.IGNORECASE))

    has_bullet_link = bool(re.search(r"^[-*]\s+\[", sample, re.MULTILINE))
    has_bare_link = bool(
        re.search(r"^\[.+?\]\(https?://", sample, re.MULTILINE)
    )
    has_any_link = has_bullet_link or has_bare_link

    parts = [f"{heading_level} {project.title}"]

    if has_blank_after_heading:
        parts.append("")

    if has_plain_desc:
        parts.append(project.description)

    if has_bullet_fields:
        if not has_plain_desc:
            parts.append("")
        if has_tech_field and project.tech_stack:
            parts.append(f"- **Tech Stack:** {', '.join(project.tech_stack)}")
        if has_tag_field and project.tags:
            parts.append(f"- **Tags:** {', '.join(project.tags)}")

    if has_any_link:
        if has_plain_desc or has_bullet_fields:
            parts.append("")
        if has_bullet_link:
            if project.repo_url:
                parts.append(f"- [View Project]({project.repo_url})")
            if project.demo_url:
                parts.append(f"- [Demo]({project.demo_url})")
        else:
            if project.repo_url:
                parts.append(f"[Repo]({project.repo_url})")
            if project.demo_url:
                parts.append(f"[Demo]({project.demo_url})")
    elif not has_any_link and not has_bullet_fields:
        if not has_plain_desc:
            parts.append(project.description)
        if project.repo_url:
            parts.append("")
            parts.append(f"[Repo]({project.repo_url})")

    return "\n".join(parts)


def _construct_plain_entry(project: ProjectConfig, sample: str = "") -> str:
    has_bold = bool(re.search(r"\*\*[^*]+\*\*", sample)) if sample else False
    has_link = bool(re.search(r"\[.+?\]\(.+?\)", sample)) if sample else False
    has_bare_url = bool(
        re.search(r"https?://\S+", sample)
    ) if sample else False

    if has_bold:
        title = f"**{project.title}**"
    else:
        title = project.title

    link = ""
    if project.repo_url:
        if has_link:
            link = f" [{project.repo_url}]({project.repo_url})"
        elif has_bare_url:
            link = f" {project.repo_url}"
        else:
            link = f" [{project.repo_url}]({project.repo_url})"

    sep = " - "
    if sample and ": " in sample:
        sep = ": "

    return f"{title}{sep}{project.description}{link}"


def detect_duplicate(content: str, project: ProjectConfig) -> bool:
    if project.repo_url and project.repo_url in content:
        return True

    title_lower = project.title.lower()
    for line in content.splitlines():
        line_lower = line.lower()
        if title_lower not in line_lower:
            continue
        bold_patterns = [
            f"**{title_lower}**",
            f"[{title_lower}]",
            f"# {title_lower}",
            f"## {title_lower}",
            f"### {title_lower}",
        ]
        if any(p in line_lower for p in bold_patterns):
            return True
        if ":" in line and '"' in line:
            return True

    return False


def _listing_content_from_default_branch(repo_path: Path, relative_path: str) -> str | None:
    if not (repo_path / ".git").is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        ref = result.stdout.strip()
        show = subprocess.run(
            ["git", "show", f"{ref}:{relative_path}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if show.returncode != 0:
            return None
        return show.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def project_already_in_portfolio(
    repo_path: Path, project: ProjectConfig, detection: DetectionResult
) -> bool:
    pl = detection.project_listing
    if not pl:
        return False
    path = repo_path / pl.file_path
    content = _listing_content_from_default_branch(repo_path, pl.file_path)
    if content is None:
        if not path.is_file():
            return False
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return False
    return detect_duplicate(content, project)


def build_profile_patch(
    content: str,
    entry: str,
    hint: ProfileReadmeHint,
    priority: str,
) -> PatchAction:
    insertion_line = compute_insertion_line(hint, priority)

    if hint.format == "table" and priority == "top":
        for pos in hint.entry_positions:
            if pos > hint.section_start_line:
                insertion_line = pos
                break

    return PatchAction(
        path="README.md",
        action="insert_before_line",
        target_line=insertion_line,
        content=entry,
    )


def create_minimal_readme(username: str) -> str:
    return f"# Hi, I'm {username}\n\n## Projects\n\n"


def detect_skills_section(content: str) -> tuple[int, int, str] | None:
    lines = content.splitlines()
    in_skills = False
    skills_start = -1
    skills_lines: list[str] = []

    for i, line in enumerate(lines):
        heading_match = re.match(r"^#{1,3}\s+(.*)", line)
        if heading_match:
            heading_text = heading_match.group(1).lower()
            if in_skills:
                return (skills_start, i - 1, "\n".join(skills_lines))
            skill_keywords = ["skill", "tech", "stack", "tool", "language"]
            if any(kw in heading_text for kw in skill_keywords):
                in_skills = True
                skills_start = i + 1
                skills_lines = []
                continue
        if in_skills:
            skills_lines.append(line)

    if in_skills and skills_lines:
        return (skills_start, len(lines) - 1, "\n".join(skills_lines))

    return None


def find_missing_tech_badges(
    skills_text: str,
    tech_stack: list[str],
) -> list[str]:
    skills_lower = skills_text.lower()
    missing: list[str] = []
    for tech in tech_stack:
        if tech.lower() not in skills_lower:
            missing.append(tech)
    return missing


def detect_badge_style(skills_text: str) -> str:
    style_match = re.search(r"style=([\w-]+)", skills_text)
    if style_match:
        return style_match.group(1)
    return "flat"


TECH_COLORS: dict[str, str] = {
    "python": "3776AB",
    "javascript": "F7DF1E",
    "typescript": "3178C6",
    "react": "61DAFB",
    "vue": "4FC08D",
    "angular": "DD0031",
    "svelte": "FF3E00",
    "next.js": "000000",
    "node.js": "339933",
    "rust": "000000",
    "go": "00ADD8",
    "java": "ED8B00",
    "c++": "00599C",
    "c#": "239120",
    "ruby": "CC342D",
    "php": "777BB4",
    "swift": "FA7343",
    "kotlin": "7F52FF",
    "dart": "0175C2",
    "docker": "2496ED",
    "kubernetes": "326CE5",
    "aws": "232F3E",
    "terraform": "7B42BC",
    "postgresql": "4169E1",
    "mongodb": "47A248",
    "redis": "DC382D",
    "graphql": "E10098",
    "tailwind": "06B6D4",
    "css": "1572B6",
    "html": "E34F26",
    "sass": "CC6699",
    "flask": "000000",
    "django": "092E20",
    "express": "000000",
    "fastapi": "009688",
    "pytorch": "EE4C2C",
    "tensorflow": "FF6F00",
}


def generate_skill_badges(
    missing_tech: list[str],
    style: str,
) -> list[str]:
    badges: list[str] = []
    for tech in missing_tech:
        tech_lower = tech.lower()
        color = TECH_COLORS.get(tech_lower, "555555")
        logo = tech_lower.replace(" ", "").replace(".", "").replace("+", "%2B").replace("#", "sharp")
        display = tech.replace(" ", "%20")
        badge_url = (
            f"https://img.shields.io/badge/"
            f"{display}-{color}?style={style}&logo={logo}&logoColor=white"
        )
        badges.append(f"![{tech}]({badge_url})")
    return badges


def build_skills_patch(
    content: str,
    project: ProjectConfig,
) -> PatchAction | None:
    result = detect_skills_section(content)
    if result is None:
        return None

    skills_start, skills_end, skills_text = result
    missing = find_missing_tech_badges(skills_text, project.tech_stack)
    if not missing:
        return None

    style = detect_badge_style(skills_text)
    new_badges = generate_skill_badges(missing, style)
    badge_line = "\n".join(new_badges)

    return PatchAction(
        path="README.md",
        action="insert_before_line",
        target_line=skills_end + 1,
        content=badge_line,
    )


def run_profile_step(
    llm: BaseChatModel,
    project: ProjectConfig,
    priority: str,
    profile_repo_path: Path,
    update_skills: bool = False,
) -> list[PatchAction]:
    readme_path = profile_repo_path / "README.md"

    if not readme_path.exists() or not readme_path.read_text(encoding="utf-8").strip():
        username = profile_repo_path.name
        minimal = create_minimal_readme(username)
        readme_path.write_text(minimal, encoding="utf-8")
        console.print(
            f"[dim]Created minimal README.md for {username}[/dim]"
        )

    content = readme_path.read_text(encoding="utf-8")

    if detect_duplicate(content, project):
        console.print(
            f"[yellow]Project '{project.title}' already exists in profile README. "
            f"Skipping.[/yellow]"
        )
        return []

    hint = parse_profile_readme(content)
    if hint is None:
        console.print(
            "[dim]No project section found in profile README. "
            "Appending a new Projects section.[/dim]"
        )
        content += "\n## Projects\n\n"
        readme_path.write_text(content, encoding="utf-8")
        hint = parse_profile_readme(content)
        if hint is None:
            console.print("[yellow]Could not parse profile README.[/yellow]")
            return []

    entry = generate_profile_entry(llm, project, hint)
    if not entry:
        console.print("[yellow]Could not generate profile entry.[/yellow]")
        return []

    patches: list[PatchAction] = []
    profile_patch = build_profile_patch(content, entry, hint, priority)
    patches.append(profile_patch)

    if update_skills:
        skills_patch = build_skills_patch(content, project)
        if skills_patch:
            patches.append(skills_patch)
            console.print("[dim]Skills badge update prepared.[/dim]")

    return patches
