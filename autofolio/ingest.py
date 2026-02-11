from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from autofolio.config import ProjectConfig
from autofolio.git_ops import cleanup_temp, clone_repo
from autofolio.llm import invoke_with_retry

console = Console()

INGEST_SYSTEM_PROMPT = """\
You are AutoFolio, a tool that extracts structured project metadata from
unstructured sources such as README files, dependency manifests, GitHub API
data, and natural-language descriptions.

You will receive context about a software project gathered from one or more
of these sources.  Your job is to produce a single ProjectConfig object with
these fields:

- title: A concise, human-readable project name (not a slug or full repo
  path). Capitalise naturally (e.g. "PinPlace", not "pinplace").
- description: A polished 1-2 sentence description of what the project does.
- repo_url: The full GitHub (or other host) URL. Leave empty if unknown.
- demo_url: A deployed/live URL if one exists. Leave empty if unknown.
- tech_stack: A list of clean, recognisable technology names
  (e.g. "React", "Tailwind CSS", "Firebase"). Map raw package names to their
  common display names. Only include meaningful technologies, not minor
  utilities.
- tags: 3-6 short domain/purpose tags (e.g. "real-time", "maps", "ai").

RULES:
- Output ONLY the structured data.  No explanation, no preamble.
- If a field cannot be determined, use the default (empty string or empty
  list).
- Prefer information from the GitHub API metadata and README over raw
  dependency names.
- For tech_stack, translate package names to display names:
  tailwindcss -> Tailwind CSS, next -> Next.js, firebase -> Firebase, etc.
"""

GITHUB_URL_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
)

DEP_FILES = [
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Gemfile",
]

README_NAMES = ["README.md", "readme.md", "README.rst", "README.txt", "README"]


def parse_github_url(url: str) -> tuple[str, str] | None:
    m = GITHUB_URL_RE.search(url)
    if m:
        owner = m.group(1)
        name = m.group(2)
        if name.endswith(".git"):
            name = name[:-4]
        return owner, name
    return None


def fetch_github_metadata(repo_url: str) -> dict:
    parsed = parse_github_url(repo_url)
    if parsed is None:
        return {}

    owner, name = parsed
    try:
        from github import Github, GithubException

        token = os.environ.get("GITHUB_TOKEN")
        g = Github(token) if token else Github()
        repo = g.get_repo(f"{owner}/{name}")
        topics = []
        try:
            topics = repo.get_topics()
        except Exception:
            pass
        return {
            "name": repo.name,
            "description": repo.description or "",
            "homepage": repo.homepage or "",
            "topics": topics,
            "language": repo.language or "",
        }
    except Exception as exc:
        console.print(
            f"[dim]GitHub API metadata fetch failed: {exc}[/dim]"
        )
        return {}


def _read_file_safe(path: Path, max_chars: int = 8000) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... (truncated)"
        return text
    except (OSError, UnicodeDecodeError):
        return None


def _read_readme(repo_path: Path) -> str | None:
    for name in README_NAMES:
        p = repo_path / name
        if p.is_file():
            return _read_file_safe(p, max_chars=4000)
    return None


def _read_dependency_info(repo_path: Path) -> str:
    parts: list[str] = []
    for dep_file in DEP_FILES:
        p = repo_path / dep_file
        if not p.is_file():
            continue
        if dep_file == "package.json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                deps = list(data.get("dependencies", {}).keys())
                dev_deps = list(data.get("devDependencies", {}).keys())
                if deps or dev_deps:
                    parts.append(
                        f"package.json dependencies: {', '.join(deps)}"
                    )
                    if dev_deps:
                        parts.append(
                            f"package.json devDependencies: {', '.join(dev_deps)}"
                        )
            except (json.JSONDecodeError, OSError):
                pass
        elif dep_file == "requirements.txt":
            content = _read_file_safe(p, max_chars=2000)
            if content:
                pkg_names = []
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        name = re.split(r"[>=<!\[]", line)[0].strip()
                        if name:
                            pkg_names.append(name)
                if pkg_names:
                    parts.append(
                        f"requirements.txt: {', '.join(pkg_names)}"
                    )
        elif dep_file == "pyproject.toml":
            content = _read_file_safe(p, max_chars=2000)
            if content:
                deps = []
                in_deps_section = False
                in_deps_list = False
                for line in content.splitlines():
                    line_stripped = line.strip()
                    if not line_stripped or line_stripped.startswith("#"):
                        if in_deps_list:
                            matches = re.findall(r'"([^"]+)"', line)
                            deps.extend(matches)
                            if "]" in line:
                                in_deps_list = False
                        continue
                    if re.match(r'^\[.*dependencies', line_stripped, re.IGNORECASE):
                        in_deps_section = True
                        in_deps_list = False
                        continue
                    if line_stripped.startswith("[") and not re.search(r'dependencies', line_stripped, re.IGNORECASE):
                        in_deps_section = False
                        in_deps_list = False
                        continue
                    if re.search(r'dependencies\s*=\s*\[', line_stripped, re.IGNORECASE):
                        in_deps_list = True
                        matches = re.findall(r'"([^"]+)"', line_stripped)
                        deps.extend(matches)
                        if "]" in line_stripped:
                            in_deps_list = False
                        continue
                    if in_deps_list:
                        matches = re.findall(r'"([^"]+)"', line_stripped)
                        deps.extend(matches)
                        if "]" in line_stripped:
                            in_deps_list = False
                    elif in_deps_section:
                        key_match = re.match(r'^([a-zA-Z0-9_-]+)\s*=', line_stripped)
                        if key_match:
                            pkg_name = key_match.group(1)
                            if pkg_name not in ["python", "version"]:
                                deps.append(pkg_name)
                if deps:
                    parts.append(
                        f"pyproject.toml dependencies: {', '.join(deps[:20])}"
                    )
        else:
            content = _read_file_safe(p, max_chars=1500)
            if content:
                parts.append(f"{dep_file}:\n{content}")

    return "\n".join(parts)


def _build_ingest_context(
    repo_url: str | None = None,
    github_meta: dict | None = None,
    readme_text: str | None = None,
    dep_info: str | None = None,
    user_description: str | None = None,
) -> str:
    sections: list[str] = []

    if repo_url:
        sections.append(f"Repository URL: {repo_url}")

    if github_meta:
        meta_lines = []
        if github_meta.get("name"):
            meta_lines.append(f"  Repo name: {github_meta['name']}")
        if github_meta.get("description"):
            meta_lines.append(
                f"  GitHub description: {github_meta['description']}"
            )
        if github_meta.get("homepage"):
            meta_lines.append(f"  Homepage/demo URL: {github_meta['homepage']}")
        if github_meta.get("topics"):
            meta_lines.append(
                f"  Topics: {', '.join(github_meta['topics'])}"
            )
        if github_meta.get("language"):
            meta_lines.append(
                f"  Primary language: {github_meta['language']}"
            )
        if meta_lines:
            sections.append("GitHub API metadata:\n" + "\n".join(meta_lines))

    if readme_text:
        sections.append(f"README content:\n{readme_text}")

    if dep_info:
        sections.append(f"Dependency information:\n{dep_info}")

    if user_description:
        sections.append(
            f"User-provided description:\n{user_description}"
        )

    return "\n\n---\n\n".join(sections)


def ingest_from_repo(
    llm: BaseChatModel,
    repo_url_or_path: str,
    extra_description: str | None = None,
) -> ProjectConfig:
    is_url = bool(GITHUB_URL_RE.search(repo_url_or_path))
    is_local = not is_url and Path(repo_url_or_path).is_dir()

    if not is_url and not is_local:
        raise ValueError(
            f"Not a valid GitHub URL or local directory: {repo_url_or_path}"
        )

    github_meta: dict = {}
    repo_url: str = repo_url_or_path if is_url else ""
    local_path: Path | None = None

    if is_url:
        with console.status("Fetching GitHub metadata...", spinner="dots"):
            github_meta = fetch_github_metadata(repo_url_or_path)

        with console.status("Cloning repo to read files...", spinner="dots"):
            temp_dir = clone_repo(repo_url_or_path)
        local_path = temp_dir
    else:
        local_path = Path(repo_url_or_path).resolve()
        temp_dir = None

    try:
        readme_text = _read_readme(local_path)
        dep_info = _read_dependency_info(local_path)

        context = _build_ingest_context(
            repo_url=repo_url,
            github_meta=github_meta,
            readme_text=readme_text,
            dep_info=dep_info,
            user_description=extra_description,
        )

        with console.status("Extracting project metadata with LLM...", spinner="dots"):
            structured_llm = llm.with_structured_output(ProjectConfig)
            config = invoke_with_retry(
                structured_llm,
                [SystemMessage(content=INGEST_SYSTEM_PROMPT), HumanMessage(content=context)],
                step_name="Project metadata extraction",
            )

        if is_url and not config.repo_url:
            config.repo_url = repo_url_or_path
        if github_meta.get("homepage") and not config.demo_url:
            config.demo_url = github_meta["homepage"]

        return config
    finally:
        if temp_dir:
            cleanup_temp(temp_dir)


def ingest_from_description(
    llm: BaseChatModel,
    text: str,
) -> ProjectConfig:
    context = _build_ingest_context(user_description=text)

    url_match = GITHUB_URL_RE.search(text)
    repo_url = url_match.group(0) if url_match else None
    if repo_url:
        context = _build_ingest_context(
            repo_url=repo_url,
            user_description=text,
        )

    with console.status("Extracting project metadata with LLM...", spinner="dots"):
        structured_llm = llm.with_structured_output(ProjectConfig)
        config = invoke_with_retry(
            structured_llm,
            [SystemMessage(content=INGEST_SYSTEM_PROMPT), HumanMessage(content=context)],
            step_name="Project metadata extraction",
        )
    if repo_url and not config.repo_url:
        config.repo_url = repo_url
    return config


def ingest_interactive(llm: BaseChatModel) -> ProjectConfig:
    console.print(
        Panel(
            "Tell me about your project.\n"
            "You can paste a GitHub URL, describe it in your own words, or both.",
            title="AutoFolio - Project Ingest",
            style="cyan",
        )
    )

    user_input = Prompt.ask("[bold]Your project[/bold]")
    if not user_input.strip():
        console.print("[red]No input provided.[/red]")
        sys.exit(1)

    url_match = GITHUB_URL_RE.search(user_input)

    if url_match:
        repo_url = url_match.group(0)
        remaining = user_input.replace(repo_url, "").strip()
        console.print(f"[dim]Detected repo URL: {repo_url}[/dim]")
        config = ingest_from_repo(
            llm, repo_url, extra_description=remaining or None
        )
    else:
        config = ingest_from_description(llm, user_input)

    if not config.repo_url:
        repo_input = Prompt.ask(
            "[bold]Repo URL[/bold] (press Enter to skip)", default=""
        )
        if repo_input.strip():
            config.repo_url = repo_input.strip()

    if not config.demo_url:
        demo_input = Prompt.ask(
            "[bold]Demo/live URL[/bold] (press Enter to skip)", default=""
        )
        if demo_input.strip():
            config.demo_url = demo_input.strip()

    return config


def _display_config(config: ProjectConfig) -> None:
    table = Table(title="Extracted Project Config", show_header=False)
    table.add_column("Field", style="bold cyan", width=14)
    table.add_column("Value")

    table.add_row("Title", config.title)
    table.add_row("Description", config.description)
    table.add_row("Repo URL", config.repo_url or "(none)")
    table.add_row("Demo URL", config.demo_url or "(none)")
    table.add_row(
        "Tech Stack",
        ", ".join(config.tech_stack) if config.tech_stack else "(none)",
    )
    table.add_row(
        "Tags",
        ", ".join(config.tags) if config.tags else "(none)",
    )

    console.print()
    console.print(table)
    console.print()


def _edit_config(config: ProjectConfig) -> ProjectConfig:
    console.print("[dim]Press Enter to keep the current value.[/dim]\n")

    title = Prompt.ask("Title", default=config.title)
    description = Prompt.ask("Description", default=config.description)
    repo_url = Prompt.ask("Repo URL", default=config.repo_url)
    demo_url = Prompt.ask("Demo URL", default=config.demo_url)

    tech_str = Prompt.ask(
        "Tech Stack (comma-separated)",
        default=", ".join(config.tech_stack),
    )
    tech_stack = [t.strip() for t in tech_str.split(",") if t.strip()]

    tags_str = Prompt.ask(
        "Tags (comma-separated)",
        default=", ".join(config.tags),
    )
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]

    return ProjectConfig(
        title=title,
        description=description,
        repo_url=repo_url,
        demo_url=demo_url,
        tech_stack=tech_stack,
        tags=tags,
    )


def confirm_config(config: ProjectConfig) -> ProjectConfig | None:
    _display_config(config)

    choice = Prompt.ask(
        "[bold]Proceed?[/bold]",
        choices=["y", "n", "edit"],
        default="y",
    )

    if choice == "n":
        console.print("[yellow]Cancelled.[/yellow]")
        return None
    elif choice == "edit":
        config = _edit_config(config)
        _display_config(config)
        final = Prompt.ask(
            "[bold]Proceed with edited config?[/bold]",
            choices=["y", "n"],
            default="y",
        )
        if final == "n":
            console.print("[yellow]Cancelled.[/yellow]")
            return None

    return config


def save_config_json(config: ProjectConfig, path: str | Path) -> None:
    path = Path(path)
    data = config.model_dump()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    console.print(f"[green]Config saved to {path}[/green]")
