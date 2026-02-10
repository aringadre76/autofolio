from __future__ import annotations

import os
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console

from autofolio.config import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_MODEL,
    AnalysisResponse,
    GenerationResponse,
    PatchAction,
    ProjectConfig,
)
from autofolio.detector import DetectionResult

console = Console()

ANALYSIS_SYSTEM_PROMPT = """\
You are AutoFolio, a tool that adds projects to existing portfolio websites.
You work with ANY portfolio, regardless of tech stack: React, Vue, Svelte, Angular,
Astro, Next.js, Nuxt, Gatsby, Hugo, Jekyll, Eleventy, plain HTML, or anything else.

You will receive:
1. The detected tech stack
2. The full file tree of the portfolio repo
3. Key file contents (package.json, main app files, HTML files, etc.)
4. A project listing hint (if detected) showing WHERE existing projects are defined
5. Metadata about a new project to add

Your job:
A) Evaluate the project (priority and resume-worthiness)
B) List which additional files you need to read (beyond what is already provided)
C) Plan exactly ONE action to add the project

CRITICAL RULES:
- files_to_read: ONLY list paths that EXIST in the file tree. Never invent paths.
- If a project listing hint is provided, your plan MUST target that file.
- Prefer "insert_after_line" to add a new entry into an existing array/list.
- For JS/TS portfolios: insert into existing arrays (const projects = [...]).
- For HTML portfolios: insert a new HTML block matching the existing pattern
  (e.g. a new <div>, <article>, <li>, or <section> matching the class/structure
  of existing project entries). Use "insert_after_line" with the closing tag of the
  last project entry as the marker.
- For markdown/content-based portfolios: use "create" to add a new content file,
  or "append" if projects are listed in a single file.
- Only use "replace" as an absolute last resort.
- Never modify package.json, tsconfig, config files, or unrelated files.
- Never suggest restructuring. Only add the new project entry.
- Your plan should have exactly ONE action targeting the project listing file.
"""

GENERATION_SYSTEM_PROMPT = """\
You are AutoFolio, a tool that generates portfolio content to add a new project.
You work with ANY tech stack: React, Vue, Svelte, Angular, Astro, Next.js, Nuxt,
Gatsby, Hugo, Jekyll, Eleventy, plain HTML, or anything else.

You will receive:
1. The detected tech stack
2. The full content of the target file
3. A sample of an existing project entry (to match the exact format)
4. The plan (which file, which action)
5. Metadata about the new project

Your job: produce a patch that adds the new project.

CRITICAL RULES:
- Your patch MUST target only the file specified in the plan.
- For "insert_after_line": the insert_after_marker MUST be an exact substring of a
  real line in the target file. Copy it character-for-character from the file content
  provided. Pick a unique line near where the new entry should go.
  - For JS/TS arrays: typically the closing brace/bracket of the last project entry.
  - For HTML files: typically the closing tag of the last project block
    (e.g. </div>, </article>, </li>, </section>).
- For "append": just provide the content to append.
- For "create": provide the full file content.
- Match the EXACT style of the existing entries: same indentation, same field names,
  same quoting style, same structure, same HTML classes and tags.
- Generate ONLY the new project entry content (not the entire file).
- The content field should contain ONLY the new entry to insert, not surrounding code.
- If the project is resume-worthy, also provide a 1-2 sentence resume_snippet.
"""

RESUME_SYSTEM_PROMPT = """\
You are AutoFolio, an expert at writing concise, impactful resume bullet points.

You will receive:
1. Project metadata (title, description, tech stack, tags)
2. Optionally, the content of an existing resume file to match its style

Generate a resume-worthy snippet for this project. If a resume file is provided,
detect its format (LaTeX, Markdown, plain text, HTML, etc.) and match its formatting
and style exactly. Otherwise, produce a plain-text bullet point suitable for any
resume format.
"""


def get_llm(provider: str | None = None) -> BaseChatModel:
    provider = provider or os.environ.get("AUTOFOLIO_LLM_PROVIDER", "ollama")

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY env var required when using openai provider"
            )
        model_name = os.environ.get("AUTOFOLIO_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        return ChatOpenAI(model=model_name, temperature=0)

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        model_name = os.environ.get("AUTOFOLIO_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOllama(model=model_name, base_url=base_url, temperature=0)

    raise ValueError(f"Unknown LLM provider: {provider}")


def run_analysis(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
) -> AnalysisResponse:
    tree_str = "\n".join(detection.file_tree)

    key_files_block = ""
    for fpath, content in detection.key_files.items():
        trimmed = content[:3000]
        if len(content) > 3000:
            trimmed += "\n... (truncated) ..."
        key_files_block += f"\n--- {fpath} ---\n{trimmed}\n"

    listing_hint = ""
    if detection.project_listing:
        pl = detection.project_listing
        is_html = pl.variable_name.startswith("(html:")
        is_directory = pl.variable_name == "(directory)"

        listing_hint = (
            f"\nPROJECT LISTING DETECTED:\n"
            f"  File: {pl.file_path}\n"
            f"  Type: {pl.variable_name}\n"
            f"  Number of existing projects: {pl.entry_count}\n"
        )
        if pl.sample_entry:
            listing_hint += f"  Last entry sample:\n{pl.sample_entry}\n"

        listing_hint += f"\nYou MUST target this file ({pl.file_path}) in your plan.\n"

        if is_html:
            listing_hint += (
                f"This is an HTML file. Use action 'insert_after_line' with the "
                f"closing tag of the last project entry as the marker. Match the "
                f"existing HTML structure, classes, and tags exactly.\n"
            )
        elif is_directory:
            listing_hint += (
                f"Projects are stored as individual files in this directory. "
                f"Use action 'create' to add a new file matching the existing format.\n"
            )
        else:
            listing_hint += (
                f"Use action 'insert_after_line' to add the new project into the "
                f"existing array.\n"
            )

    user_content = (
        f"Detected stack: {detection.stack}\n\n"
        f"File tree:\n{tree_str}\n\n"
        f"Key file contents:{key_files_block}\n"
        f"{listing_hint}\n"
        f"Project to add:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n"
    )

    structured_llm = llm.with_structured_output(AnalysisResponse)
    response = structured_llm.invoke([
        SystemMessage(content=ANALYSIS_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ])
    return response


def validate_analysis(
    analysis: AnalysisResponse,
    detection: DetectionResult,
) -> AnalysisResponse:
    tree_set = set(detection.file_tree)

    valid_files = [f for f in analysis.files_to_read if f in tree_set]
    dropped = [f for f in analysis.files_to_read if f not in tree_set]
    for f in dropped:
        console.print(f"[yellow]  Dropped non-existent file from read list: {f}[/yellow]")

    if detection.project_listing:
        pl_file = detection.project_listing.file_path
        if pl_file not in valid_files:
            valid_files.append(pl_file)
            console.print(f"[dim]  Auto-added project listing file: {pl_file}[/dim]")

    valid_plan = []
    for action in analysis.plan:
        if action.action in ("replace", "append", "insert_after_line"):
            if action.path not in tree_set:
                console.print(
                    f"[yellow]  Dropped plan action for non-existent file: "
                    f"{action.path}[/yellow]"
                )
                continue
        valid_plan.append(action)

    if detection.project_listing and not any(
        a.path == detection.project_listing.file_path for a in valid_plan
    ):
        from autofolio.config import PlannedAction
        valid_plan = [
            PlannedAction(
                path=detection.project_listing.file_path,
                action="insert_after_line",
                explain=(
                    f"Insert new project entry into the "
                    f"{detection.project_listing.variable_name} array"
                ),
            )
        ]
        console.print(
            f"[dim]  Auto-corrected plan to target: "
            f"{detection.project_listing.file_path}[/dim]"
        )

    analysis.files_to_read = valid_files
    analysis.plan = valid_plan
    return analysis


def run_generation(
    llm: BaseChatModel,
    project: ProjectConfig,
    analysis: AnalysisResponse,
    file_contents: dict[str, str],
    detection: DetectionResult,
) -> GenerationResponse:
    plan_lines = []
    for action in analysis.plan:
        plan_lines.append(
            f"  - {action.path}: {action.action} -- {action.explain}"
        )

    files_block = ""
    for fpath, content in file_contents.items():
        files_block += f"\n--- {fpath} ---\n{content}\n"

    listing_context = ""
    if detection.project_listing:
        pl = detection.project_listing
        is_html = pl.variable_name.startswith("(html:")

        listing_context = (
            f"\nEXISTING PROJECT ENTRY FORMAT (you MUST match this exactly):\n"
            f"Type: {pl.variable_name}\n"
        )
        if pl.sample_entry:
            listing_context += f"Sample entry:\n{pl.sample_entry}\n\n"

        if is_html:
            listing_context += (
                f"This is an HTML portfolio. Your new entry MUST use the same "
                f"HTML tags, classes, structure, and indentation as above.\n"
                f"For the insert_after_marker, use the closing tag of the LAST "
                f"project entry in the file content.\n"
            )
        else:
            listing_context += (
                f"Your new entry MUST use the same fields, same indentation, "
                f"same quoting style, and same structure as above.\n"
                f"For the insert_after_marker, find the LAST entry's closing line "
                f"in the file content and use it as the marker.\n"
            )

    user_content = (
        f"Detected stack: {detection.stack}\n\n"
        f"Analysis plan:\n"
        f"  Priority: {analysis.evaluation.portfolio_priority}\n"
        f"  Resume-worthy: {analysis.evaluation.resume_worthy}\n"
        f"  Reason: {analysis.evaluation.reason}\n\n"
        f"Planned actions:\n"
        + "\n".join(plan_lines) + "\n\n"
        f"{listing_context}\n"
        f"File contents (these are the ONLY files that exist):{files_block}\n\n"
        f"Project to add:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"REMINDER: The insert_after_marker must be an EXACT substring of a "
        f"line from the file content above. The content field should contain "
        f"ONLY the new entry to insert.\n"
    )

    structured_llm = llm.with_structured_output(GenerationResponse)
    response = structured_llm.invoke([
        SystemMessage(content=GENERATION_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ])
    return response


def validate_generation(
    generation: GenerationResponse,
    file_contents: dict[str, str],
    detection: DetectionResult,
) -> GenerationResponse:
    tree_set = set(detection.file_tree)
    valid_patches: list[PatchAction] = []

    for patch in generation.patch:
        if patch.action in ("replace", "append", "insert_after_line"):
            if patch.path not in tree_set:
                console.print(
                    f"[yellow]  Dropped patch for non-existent file: "
                    f"{patch.path}[/yellow]"
                )
                continue

        if patch.action == "insert_after_line":
            if not patch.insert_after_marker:
                console.print(
                    f"[yellow]  Patch for {patch.path} has no marker, "
                    f"attempting auto-fix...[/yellow]"
                )
                patch = _auto_fix_marker(patch, file_contents, detection)
                if patch is None:
                    continue

            content = file_contents.get(patch.path, "")
            if content and patch.insert_after_marker:
                if patch.insert_after_marker not in content:
                    console.print(
                        f"[yellow]  Marker not found in {patch.path}: "
                        f"{patch.insert_after_marker!r}[/yellow]"
                    )
                    console.print(
                        f"[yellow]  Attempting auto-fix...[/yellow]"
                    )
                    patch = _auto_fix_marker(patch, file_contents, detection)
                    if patch is None:
                        continue

        valid_patches.append(patch)

    if not valid_patches and detection.project_listing:
        console.print(
            "[yellow]  All patches invalid. Generating fallback patch...[/yellow]"
        )
        fallback = _build_fallback_patch(detection)
        if fallback:
            valid_patches.append(fallback)

    generation.patch = valid_patches
    return generation


def _auto_fix_marker(
    patch: PatchAction,
    file_contents: dict[str, str],
    detection: DetectionResult,
) -> PatchAction | None:
    if not (detection.project_listing and patch.path == detection.project_listing.file_path):
        return None

    content = file_contents.get(patch.path, "")
    if not content:
        return None

    pl = detection.project_listing
    is_html = pl.variable_name.startswith("(html:")

    if is_html:
        if pl.last_entry_marker and pl.last_entry_marker in content:
            marker = pl.last_entry_marker
        else:
            marker = None
    else:
        marker = _find_last_entry_closing(content, pl.variable_name)

    if marker:
        console.print(
            f"[dim]  Auto-fixed marker to: {marker!r}[/dim]"
        )
        return PatchAction(
            path=patch.path,
            action=patch.action,
            insert_after_marker=marker,
            content=patch.content,
        )
    return None


def _find_last_entry_closing(content: str, variable_name: str) -> str | None:
    import re
    pattern = re.compile(
        rf"(?:export\s+)?(?:const|let|var)\s+{re.escape(variable_name)}\s*"
        rf"(?::\s*[^=]+)?\s*=\s*\[",
        re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return None

    bracket_start = content.index("[", match.start())
    depth = 0
    last_brace_close_line = None
    i = bracket_start
    while i < len(content):
        ch = content[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                break
        elif ch == "}":
            line_start = content.rfind("\n", 0, i) + 1
            line_end = content.find("\n", i)
            if line_end == -1:
                line_end = len(content)
            last_brace_close_line = content[line_start:line_end].rstrip()
        i += 1

    if last_brace_close_line:
        stripped = last_brace_close_line.strip()
        if stripped:
            return stripped

    return None


def _build_fallback_patch(detection: DetectionResult) -> PatchAction | None:
    return None


def generate_focused_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    priority: str = "bottom",
) -> PatchAction | None:
    if not detection.project_listing:
        return None

    pl = detection.project_listing
    file_content = detection.key_files.get(pl.file_path, "")
    if not file_content:
        return None

    is_html = pl.variable_name.startswith("(html:")
    is_directory = pl.variable_name == "(directory)"

    if is_directory:
        return None

    if is_html:
        return _generate_focused_html_entry(
            llm, project, detection, pl, file_content
        )

    return _generate_focused_code_entry(
        llm, project, detection, pl, file_content, priority
    )


def _generate_focused_code_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
    file_content: str,
    priority: str = "bottom",
) -> PatchAction | None:
    sample_fields = _extract_field_names(pl.sample_entry)

    prompt = (
        f"You are adding a new project entry to a {detection.stack} portfolio.\n\n"
        f"Here is an existing entry from the '{pl.variable_name}' array "
        f"in {pl.file_path}:\n\n"
        f"{pl.sample_entry}\n\n"
        f"Generate ONE new entry in the EXACT same format for this project:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Output ONLY the new entry object (starting with {{ and ending with }},).\n"
        f"The entry MUST only use these fields: {', '.join(sample_fields)}.\n"
        f"Do NOT add any fields that are not in the sample entry above.\n"
        f"Match the indentation, field names, quoting style, and structure exactly.\n"
        f"Do not include any explanation, just the code.\n"
    )

    response = llm.invoke([
        SystemMessage(
            content="You output code snippets only. No explanation. No markdown fences."
        ),
        HumanMessage(content=prompt),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    if not raw.startswith("{"):
        idx = raw.find("{")
        if idx >= 0:
            raw = raw[idx:]
        else:
            return None

    closing_result = _find_array_closing(file_content, pl.variable_name)
    if not closing_result:
        return None
    closing_marker, closing_line_num = closing_result

    entry_lines = _find_entry_line_numbers(file_content, pl.variable_name)

    if priority == "top" and entry_lines:
        target_line = entry_lines[0]
        placement_label = "top"
    elif priority == "middle" and len(entry_lines) >= 2:
        mid_idx = len(entry_lines) // 2
        target_line = entry_lines[mid_idx]
        placement_label = f"middle (position {mid_idx + 1} of {len(entry_lines) + 1})"
    else:
        target_line = closing_line_num
        placement_label = "bottom"

    console.print(
        f"[dim]  Placement: {placement_label} "
        f"(priority: {priority})[/dim]"
    )

    entry = raw.strip()
    if not entry.endswith(","):
        if entry.endswith("}"):
            entry = entry + ","
        else:
            entry = entry.rstrip().rstrip(",") + ","

    indent = _detect_entry_indent(pl.sample_entry)
    raw_lines = entry.splitlines()
    raw_indent = _detect_current_indent(raw_lines)

    indented_lines = []
    for line in raw_lines:
        if not line.strip():
            indented_lines.append(line)
            continue
        stripped = line.lstrip()
        current_leading = len(line) - len(stripped)
        extra = current_leading - len(raw_indent)
        if extra < 0:
            extra = 0
        indented_lines.append(indent + " " * extra + stripped)
    indented = "\n".join(indented_lines)

    return PatchAction(
        path=pl.file_path,
        action="insert_before_line",
        insert_after_marker=closing_marker,
        target_line=target_line,
        content=indented,
    )


def _generate_focused_html_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
    file_content: str,
) -> PatchAction | None:
    prompt = (
        f"You are adding a new project entry to a {detection.stack} portfolio "
        f"that uses HTML.\n\n"
        f"Here is an existing project entry from {pl.file_path}:\n\n"
        f"{pl.sample_entry}\n\n"
        f"Generate ONE new HTML block in the EXACT same format for this project:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Output ONLY the new HTML block.\n"
        f"Use the same tags, classes, structure, and indentation as the sample.\n"
        f"Do not include any explanation, just the HTML.\n"
    )

    response = llm.invoke([
        SystemMessage(
            content="You output HTML snippets only. No explanation. No markdown fences."
        ),
        HumanMessage(content=prompt),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    if not raw.strip().startswith("<"):
        idx = raw.find("<")
        if idx >= 0:
            raw = raw[idx:]
        else:
            return None

    marker = pl.last_entry_marker
    if not marker:
        return None

    marker_line_num = None
    for i, line in enumerate(file_content.splitlines(), 1):
        if marker in line:
            marker_line_num = i

    if marker_line_num is None:
        return None

    indent = _detect_html_indent(pl.sample_entry)
    raw_lines = raw.splitlines()
    base_indent = _detect_html_indent_amount(raw_lines)
    indented_lines = []
    for line in raw_lines:
        if not line.strip():
            indented_lines.append(line)
            continue
        stripped = line.lstrip()
        current_leading = len(line) - len(stripped)
        extra = current_leading - base_indent
        if extra < 0:
            extra = 0
        indented_lines.append(indent + " " * extra + stripped)
    indented = "\n".join(indented_lines)

    return PatchAction(
        path=pl.file_path,
        action="insert_after_line",
        insert_after_marker=marker,
        content=indented,
    )


def _detect_html_indent(sample_entry: str) -> str:
    for line in sample_entry.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("<"):
            return line[: len(line) - len(stripped)]
    return "  "


def _detect_html_indent_amount(lines: list[str]) -> int:
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("<"):
            return len(line) - len(stripped)
    return 0


def _extract_field_names(sample_entry: str) -> list[str]:
    import re
    fields = re.findall(r'(\w+)\s*:', sample_entry)
    seen = set()
    result = []
    for f in fields:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result


def _detect_entry_indent(sample_entry: str) -> str:
    for line in sample_entry.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("{"):
            return line[: len(line) - len(stripped)]
    return "  "


def _detect_current_indent(lines: list[str]) -> str:
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("{"):
            return line[: len(line) - len(stripped)]
    return ""


def _find_entry_line_numbers(content: str, variable_name: str) -> list[int]:
    import re
    pattern = re.compile(
        rf"(?:export\s+)?(?:const|let|var)\s+{re.escape(variable_name)}\s*"
        rf"(?::\s*[^=]+)?\s*=\s*\[",
        re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return []

    bracket_start = content.index("[", match.start())
    entry_starts: list[int] = []
    depth = 0
    i = bracket_start
    while i < len(content):
        ch = content[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                break
        elif ch == "{" and depth == 1:
            line_num = content[:i].count("\n") + 1
            entry_starts.append(line_num)
        i += 1

    return entry_starts


def _find_array_closing(content: str, variable_name: str) -> tuple[str, int] | None:
    import re
    pattern = re.compile(
        rf"(?:export\s+)?(?:const|let|var)\s+{re.escape(variable_name)}\s*"
        rf"(?::\s*[^=]+)?\s*=\s*\[",
        re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return None

    bracket_start = content.index("[", match.start())
    depth = 0
    i = bracket_start
    while i < len(content):
        ch = content[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                line_num = content[:i].count("\n") + 1
                line_start = content.rfind("\n", 0, i) + 1
                line_end = content.find("\n", i)
                if line_end == -1:
                    line_end = len(content)
                closing_line = content[line_start:line_end].strip()
                return closing_line, line_num
        i += 1

    return None


def generate_resume_snippet(
    llm: BaseChatModel,
    project: ProjectConfig,
    resume_content: str | None = None,
) -> str:
    user_content = (
        f"Project:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n"
    )
    if resume_content:
        user_content += f"\nExisting resume content:\n{resume_content}\n"
        user_content += (
            "\nDetect the format of this resume (LaTeX, Markdown, HTML, plain text, "
            "etc.) and match its formatting and style exactly."
        )
    else:
        user_content += (
            "\nNo resume file provided. Generate a plain-text bullet point "
            "suitable for any resume format."
        )

    response = llm.invoke([
        SystemMessage(content=RESUME_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ])
    return response.content


def read_requested_files(
    repo_path: Path, file_paths: list[str]
) -> dict[str, str]:
    contents: dict[str, str] = {}
    for fpath in file_paths:
        full = (repo_path / fpath).resolve()
        if not str(full).startswith(str(repo_path.resolve())):
            console.print(f"[yellow]Skipping path outside repo: {fpath}[/yellow]")
            continue
        if full.is_file():
            try:
                contents[fpath] = full.read_text(encoding="utf-8")
            except OSError as e:
                console.print(f"[yellow]Could not read {fpath}: {e}[/yellow]")
        else:
            console.print(f"[yellow]File not found: {fpath}[/yellow]")
    return contents
