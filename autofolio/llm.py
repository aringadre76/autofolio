from __future__ import annotations

import os
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console
from tenacity import retry, stop_after_attempt, wait_exponential

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
Astro, Next.js, Nuxt, Gatsby, Hugo, Jekyll, Eleventy, plain HTML, TypeScript with
Tailwind, Remix, SvelteKit, or anything else. You also handle data-driven portfolios
using JSON, YAML, TOML data files, and markdown/MDX content files.

You will receive:
1. The detected tech stack
2. The full file tree of the portfolio repo
3. Key file contents (package.json, main app files, data files, HTML files, etc.)
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
- For JS/TS portfolios (including TypeScript + Tailwind): insert into existing
  arrays (const projects = [...], export default [...], module.exports = [...]).
- For HTML portfolios: insert a new HTML block matching the existing pattern
  (e.g. a new <div>, <article>, <li>, or <section> matching the class/structure
  of existing project entries). Use "insert_after_line" with the closing tag of the
  last project entry as the marker.
- For JSON data files: use "replace" to rewrite the file with the new entry added
  to the array, or "append" if appending is simpler.
- For YAML data files: use "append" to add a new list item, or "insert_before_line"
  for top/middle placement.
- For markdown/MDX content files: use "append" to add a new section, or "create"
  to add a new content file in a content directory.
- For content directories (projects stored as individual files): use "create" to
  add a new file matching the existing format.
- Only use "replace" for entire-file rewrites when structurally necessary (like JSON).
- Never modify package.json, tsconfig, tailwind.config, vite.config, or unrelated files.
- Never suggest restructuring. Only add the new project entry.
- Your plan should have exactly ONE action targeting the project listing file.
"""

GENERATION_SYSTEM_PROMPT = """\
You are AutoFolio, a tool that generates portfolio content to add a new project.
You work with ANY tech stack: React, Vue, Svelte, Angular, Astro, Next.js, Nuxt,
Gatsby, Hugo, Jekyll, Eleventy, plain HTML, TypeScript with Tailwind, Remix,
SvelteKit, or anything else. You also handle data files (JSON, YAML, TOML) and
markdown/MDX content files.

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
  - For JS/TS arrays (including export default and module.exports): typically the
    closing brace/bracket of the last project entry.
  - For HTML files: typically the closing tag of the last project block
    (e.g. </div>, </article>, </li>, </section>).
- For "replace": used for JSON data files when rewriting the full file with the
  new entry inserted into the array. Provide the complete new file content.
- For "append": just provide the content to append (for YAML, Markdown, etc.).
- For "create": provide the full file content (for new content files in directories).
- Match the EXACT style of the existing entries: same indentation, same field names,
  same quoting style, same structure, same HTML classes and tags, same Tailwind
  classes if applicable.
- For JSON: output valid JSON only. Match the schema of existing entries exactly.
- For YAML: output valid YAML only. Match field names and indentation exactly.
- For Markdown/MDX: match heading levels, formatting, and frontmatter structure.
- Generate ONLY the new project entry content (not the entire file), unless the
  action is "replace" or "create".
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


def _get_max_retries() -> int:
    return int(os.environ.get("AUTOFOLIO_MAX_RETRIES", "3"))


def _retry_log(step_name: str):
    def _log(retry_state):
        attempt = retry_state.attempt_number
        max_retries = _get_max_retries()
        exc = retry_state.outcome.exception()
        console.print(
            f"[yellow]  {step_name} failed (attempt {attempt}/{max_retries}): "
            f"{type(exc).__name__}: {exc}[/yellow]"
        )
        console.print(f"[yellow]  Retrying...[/yellow]")
    return _log


def invoke_with_retry(invocable, messages, step_name: str = "LLM call"):
    max_retries = _get_max_retries()

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
        before_sleep=_retry_log(step_name),
    )
    def _call():
        return invocable.invoke(messages)

    try:
        return _call()
    except Exception as exc:
        console.print(
            f"[bold red]{step_name} failed after {max_retries} "
            f"attempts: {type(exc).__name__}: {exc}[/bold red]"
        )
        raise RuntimeError(
            f"{step_name} failed after {max_retries} attempts: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


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

        is_json = pl.variable_name == "(json-array)"
        is_yaml = pl.variable_name == "(yaml-list)"
        is_toml = pl.variable_name == "(toml-array)"
        is_markdown = pl.variable_name == "(markdown)"

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
        elif is_json:
            listing_hint += (
                f"This is a JSON data file containing an array of projects. "
                f"Use action 'replace' to rewrite the entire file with the new "
                f"project entry added to the array. Match field names exactly.\n"
            )
        elif is_yaml:
            listing_hint += (
                f"This is a YAML data file containing a list of projects. "
                f"Use action 'append' to add the new project as a list item. "
                f"Match field names and indentation exactly.\n"
            )
        elif is_toml:
            listing_hint += (
                f"This is a TOML data file with project entries. "
                f"Use action 'append' to add a new [[projects]] section. "
                f"Match field names exactly.\n"
            )
        elif is_markdown:
            listing_hint += (
                f"This is a Markdown file listing projects. "
                f"Use action 'append' to add a new project section, "
                f"matching the heading level and formatting of existing entries.\n"
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
    response = invoke_with_retry(
        structured_llm,
        [SystemMessage(content=ANALYSIS_SYSTEM_PROMPT), HumanMessage(content=user_content)],
        step_name="Portfolio analysis",
    )
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
        pl = detection.project_listing
        if pl.variable_name == "(json-array)":
            default_action = "replace"
        elif pl.variable_name in ("(yaml-list)", "(markdown)"):
            default_action = "append"
        elif pl.variable_name == "(directory)":
            default_action = "create"
        else:
            default_action = "insert_after_line"

        valid_plan = [
            PlannedAction(
                path=pl.file_path,
                action=default_action,
                explain=(
                    f"Insert new project entry into the "
                    f"{pl.variable_name} listing"
                ),
            )
        ]
        console.print(
            f"[dim]  Auto-corrected plan to target: "
            f"{pl.file_path}[/dim]"
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
        is_json = pl.variable_name == "(json-array)"
        is_yaml = pl.variable_name == "(yaml-list)"
        is_markdown = pl.variable_name == "(markdown)"

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
        elif is_json:
            listing_context += (
                f"This is a JSON data file. Generate a valid JSON object matching "
                f"the exact same field names and structure as the sample above.\n"
                f"For 'replace' action, provide the complete rewritten file content "
                f"with the new entry added to the array.\n"
            )
        elif is_yaml:
            listing_context += (
                f"This is a YAML data file. Generate a valid YAML list entry "
                f"matching the exact same field names and indentation as above.\n"
                f"For 'append' action, provide the new list item content.\n"
            )
        elif is_markdown:
            listing_context += (
                f"This is a Markdown file listing projects. Generate a new section "
                f"matching the exact same heading level, formatting, and structure.\n"
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

    is_html = pl.variable_name.startswith("(html:")
    is_directory = pl.variable_name == "(directory)"
    is_data = pl.variable_name in ("(json-array)", "(yaml-list)", "(toml-array)")
    is_markdown = pl.variable_name == "(markdown)"

    if is_directory:
        return _generate_focused_directory_entry(
            llm, project, detection, pl
        )

    if not file_content:
        return None

    if is_html:
        return _generate_focused_html_entry(
            llm, project, detection, pl, file_content
        )

    if is_data:
        return _generate_focused_data_entry(
            llm, project, detection, pl, file_content, priority
        )

    if is_markdown:
        return _generate_focused_markdown_entry(
            llm, project, detection, pl, file_content, priority
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


def _generate_focused_data_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
    file_content: str,
    priority: str = "bottom",
) -> PatchAction | None:
    ext = Path(pl.file_path).suffix.lower()

    if ext == ".json":
        return _generate_focused_json_entry(
            llm, project, detection, pl, file_content, priority
        )
    elif ext in (".yaml", ".yml"):
        return _generate_focused_yaml_entry(
            llm, project, detection, pl, file_content, priority
        )
    else:
        return _generate_focused_generic_data_entry(
            llm, project, detection, pl, file_content
        )


def _generate_focused_json_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
    file_content: str,
    priority: str = "bottom",
) -> PatchAction | None:
    prompt = (
        f"You are adding a new project entry to a JSON data file used "
        f"by a {detection.stack} portfolio.\n\n"
        f"Here is a sample existing entry from {pl.file_path}:\n\n"
        f"{pl.sample_entry}\n\n"
        f"Generate ONE new JSON object in the EXACT same format for this project:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Output ONLY the new JSON object (starting with {{ and ending with }}).\n"
        f"Use the EXACT same field names, structure, and nesting as the sample.\n"
        f"Do NOT add any fields that are not in the sample entry above.\n"
        f"Do not include any explanation, just the JSON.\n"
    )

    response = llm.invoke([
        SystemMessage(
            content="You output JSON snippets only. No explanation. No markdown fences."
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

    last_brace = raw.rfind("}")
    if last_brace >= 0:
        raw = raw[: last_brace + 1]

    try:
        import json
        json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        console.print("[yellow]  LLM JSON entry was invalid, attempting fix...[/yellow]")
        return None

    import json as json_mod
    try:
        data = json_mod.loads(file_content)
    except (json_mod.JSONDecodeError, ValueError):
        return PatchAction(
            path=pl.file_path,
            action="append",
            content=raw,
        )

    new_entry = json_mod.loads(raw)

    if isinstance(data, list):
        if priority == "top":
            data.insert(0, new_entry)
        elif priority == "middle":
            mid = len(data) // 2
            data.insert(mid, new_entry)
        else:
            data.append(new_entry)
        new_content = json_mod.dumps(data, indent=2, ensure_ascii=False) + "\n"
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                if priority == "top":
                    value.insert(0, new_entry)
                elif priority == "middle":
                    mid = len(value) // 2
                    value.insert(mid, new_entry)
                else:
                    value.append(new_entry)
                break
        new_content = json_mod.dumps(data, indent=2, ensure_ascii=False) + "\n"
    else:
        return None

    console.print(f"[dim]  Placement: {priority}[/dim]")

    return PatchAction(
        path=pl.file_path,
        action="replace",
        content=new_content,
    )


def _generate_focused_yaml_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
    file_content: str,
    priority: str = "bottom",
) -> PatchAction | None:
    prompt = (
        f"You are adding a new project entry to a YAML data file used "
        f"by a {detection.stack} portfolio.\n\n"
        f"Here is the full file content of {pl.file_path}:\n\n"
        f"{file_content}\n\n"
        f"And here is a sample existing entry:\n\n"
        f"{pl.sample_entry}\n\n"
        f"Generate ONE new YAML entry in the EXACT same format for this project:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Output ONLY the new YAML entry (starting with '- ').\n"
        f"Use the EXACT same field names, indentation, and structure.\n"
        f"Do NOT add any fields not in the sample. No explanation.\n"
    )

    response = llm.invoke([
        SystemMessage(
            content="You output YAML snippets only. No explanation. No markdown fences."
        ),
        HumanMessage(content=prompt),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    if not raw.strip().startswith("-"):
        idx = raw.find("- ")
        if idx >= 0:
            raw = raw[idx:]
        else:
            raw = f"- title: {project.title}\n  description: {project.description}\n"
            if project.repo_url:
                raw += f"  url: {project.repo_url}\n"
            if project.tech_stack:
                raw += f"  tech: [{', '.join(project.tech_stack)}]\n"

    content = raw.rstrip() + "\n"

    if priority == "bottom" or priority == "middle":
        return PatchAction(
            path=pl.file_path,
            action="append",
            content="\n" + content,
        )
    else:
        lines = file_content.splitlines(keepends=True)
        first_entry_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith("- "):
                first_entry_idx = i + 1
                break
        if first_entry_idx is not None:
            return PatchAction(
                path=pl.file_path,
                action="insert_before_line",
                target_line=first_entry_idx,
                content=content,
            )
        return PatchAction(
            path=pl.file_path,
            action="append",
            content="\n" + content,
        )


def _generate_focused_generic_data_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
    file_content: str,
) -> PatchAction | None:
    prompt = (
        f"You are adding a new project entry to a data file used "
        f"by a {detection.stack} portfolio.\n\n"
        f"Here is the full file content of {pl.file_path}:\n\n"
        f"{file_content}\n\n"
        f"Generate ONE new entry in the EXACT same format for this project:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Output ONLY the new entry. Match the existing format exactly.\n"
    )

    response = llm.invoke([
        SystemMessage(
            content="You output data snippets only. No explanation. No markdown fences."
        ),
        HumanMessage(content=prompt),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    if not raw:
        return None

    return PatchAction(
        path=pl.file_path,
        action="append",
        content="\n" + raw + "\n",
    )


def _generate_focused_markdown_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
    file_content: str,
    priority: str = "bottom",
) -> PatchAction | None:
    prompt = (
        f"You are adding a new project entry to a Markdown file used "
        f"by a {detection.stack} portfolio.\n\n"
        f"Here is the full file content of {pl.file_path}:\n\n"
        f"{file_content}\n\n"
    )
    if pl.sample_entry:
        prompt += (
            f"Here is a sample existing project entry:\n\n"
            f"{pl.sample_entry}\n\n"
        )
    prompt += (
        f"Generate ONE new entry in the EXACT same format for this project:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Output ONLY the new entry. Match the heading level, structure, "
        f"and formatting of existing entries exactly.\n"
        f"Do not include any explanation, just the markdown.\n"
    )

    response = llm.invoke([
        SystemMessage(
            content="You output Markdown snippets only. No explanation. No markdown code fences."
        ),
        HumanMessage(content=prompt),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    if not raw:
        return None

    content = "\n" + raw + "\n"

    if priority == "top":
        import re
        lines = file_content.splitlines(keepends=True)
        first_entry = None
        for i, line in enumerate(lines):
            if re.match(r"^#{2,3}\s+\S", line):
                first_entry = i + 1
                break
        if first_entry is not None:
            return PatchAction(
                path=pl.file_path,
                action="insert_before_line",
                target_line=first_entry,
                content=content.lstrip("\n") + "\n",
            )

    return PatchAction(
        path=pl.file_path,
        action="append",
        content=content,
    )


def _generate_focused_directory_entry(
    llm: BaseChatModel,
    project: ProjectConfig,
    detection: DetectionResult,
    pl,
) -> PatchAction | None:
    repo_path = Path(pl.file_path)
    existing_files = [
        f for f in detection.file_tree if f.startswith(str(repo_path) + "/")
    ]

    sample_content = ""
    sample_file = ""
    for fpath in existing_files:
        content = detection.key_files.get(fpath, "")
        if content:
            sample_content = content
            sample_file = fpath
            break

    slug = project.title.lower().strip()
    slug = __import__("re").sub(r"[^a-z0-9]+", "-", slug).strip("-")

    ext = ".md"
    if existing_files:
        ext = Path(existing_files[0]).suffix

    new_filename = f"{repo_path}/{slug}{ext}"

    prompt = (
        f"You are adding a new project to a {detection.stack} portfolio.\n"
        f"Projects are stored as individual files in the '{pl.file_path}' directory.\n\n"
    )
    if sample_content:
        prompt += (
            f"Here is an existing project file ({sample_file}):\n\n"
            f"{sample_content}\n\n"
        )
    prompt += (
        f"Generate the COMPLETE file content for a new project file:\n"
        f"  Title: {project.title}\n"
        f"  Description: {project.description}\n"
        f"  Repo URL: {project.repo_url}\n"
        f"  Demo URL: {project.demo_url}\n"
        f"  Tech Stack: {', '.join(project.tech_stack)}\n"
        f"  Tags: {', '.join(project.tags)}\n\n"
        f"Match the EXACT format, frontmatter structure, and style of the sample.\n"
        f"Output the complete file content only. No explanation.\n"
    )

    response = llm.invoke([
        SystemMessage(
            content="You output file content only. No explanation. No wrapping markdown fences."
        ),
        HumanMessage(content=prompt),
    ])

    raw = response.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    if not raw:
        raw = f"---\ntitle: {project.title}\ndescription: {project.description}\n"
        if project.repo_url:
            raw += f"url: {project.repo_url}\n"
        if project.tech_stack:
            raw += f"tags: [{', '.join(project.tech_stack)}]\n"
        raw += f"---\n\n# {project.title}\n\n{project.description}\n"

    return PatchAction(
        path=new_filename,
        action="create",
        content=raw + "\n",
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
