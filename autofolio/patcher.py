from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax

from autofolio.config import PatchAction

console = Console()

ALLOWED_ACTIONS = {"create", "replace", "append", "insert_after_line", "insert_before_line"}


class PatchError(Exception):
    pass


def _sanitize_path(repo_root: Path, relative_path: str) -> Path:
    cleaned = Path(relative_path)
    if cleaned.is_absolute():
        raise PatchError(f"Patch path must be relative, got: {relative_path}")
    resolved = (repo_root / cleaned).resolve()
    if not str(resolved).startswith(str(repo_root.resolve())):
        raise PatchError(f"Path escapes repo root: {relative_path}")
    return resolved


def _guess_lexer(path: Path) -> str:
    suffix_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".md": "markdown",
        ".mdx": "markdown",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "scss",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".svelte": "html",
        ".vue": "html",
        ".astro": "html",
        ".njk": "html",
        ".ejs": "html",
        ".hbs": "html",
        ".liquid": "html",
        ".pug": "pug",
        ".php": "php",
        ".erb": "html",
        ".rs": "rust",
        ".go": "go",
        ".rb": "ruby",
    }
    return suffix_map.get(path.suffix, "text")


def preview_patches(repo_root: Path, patches: list[PatchAction]) -> None:
    for patch in patches:
        target = _sanitize_path(repo_root, patch.path)
        console.print(f"\n[bold cyan]--- {patch.path} ({patch.action}) ---[/bold cyan]")

        if patch.action == "create":
            console.print("[green]+ new file[/green]")
        elif patch.action == "replace":
            console.print("[yellow]~ full file replacement[/yellow]")
        elif patch.action == "append":
            console.print("[green]+ append to end of file[/green]")
        elif patch.action == "insert_after_line":
            marker = patch.insert_after_marker or "(no marker)"
            console.print(f"[green]+ insert after:[/green] {marker}")

        lexer = _guess_lexer(target)
        syntax = Syntax(patch.content, lexer, theme="monokai", line_numbers=True)
        console.print(syntax)


def apply_patches(repo_root: Path, patches: list[PatchAction]) -> list[Path]:
    repo_root = repo_root.resolve()
    modified: list[Path] = []

    for patch in patches:
        if patch.action not in ALLOWED_ACTIONS:
            raise PatchError(f"Unknown action: {patch.action}")

        target = _sanitize_path(repo_root, patch.path)

        if patch.action == "create":
            if target.exists():
                raise PatchError(f"File already exists (action=create): {patch.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch.content, encoding="utf-8")

        elif patch.action == "replace":
            if not target.exists():
                raise PatchError(f"File not found (action=replace): {patch.path}")
            target.write_text(patch.content, encoding="utf-8")

        elif patch.action == "append":
            if not target.exists():
                raise PatchError(f"File not found (action=append): {patch.path}")
            with open(target, "a", encoding="utf-8") as f:
                f.write(patch.content)

        elif patch.action == "insert_after_line":
            if not target.exists():
                raise PatchError(f"File not found (action=insert_after_line): {patch.path}")
            if not patch.insert_after_marker:
                raise PatchError(
                    f"insert_after_line requires insert_after_marker for: {patch.path}"
                )
            original = target.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            insert_idx = None
            for i, line in enumerate(lines):
                if patch.insert_after_marker in line:
                    insert_idx = i + 1
            if insert_idx is None:
                raise PatchError(
                    f"Marker not found in {patch.path}: {patch.insert_after_marker!r}"
                )
            content_to_insert = patch.content
            if not content_to_insert.endswith("\n"):
                content_to_insert += "\n"
            lines.insert(insert_idx, content_to_insert)
            target.write_text("".join(lines), encoding="utf-8")

        elif patch.action == "insert_before_line":
            if not target.exists():
                raise PatchError(f"File not found (action=insert_before_line): {patch.path}")
            original = target.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)

            if patch.target_line is not None:
                insert_idx = patch.target_line - 1
                if insert_idx < 0 or insert_idx > len(lines):
                    raise PatchError(
                        f"target_line {patch.target_line} out of range "
                        f"for {patch.path} ({len(lines)} lines)"
                    )
            elif patch.insert_after_marker:
                insert_idx = None
                for i, line in enumerate(lines):
                    if patch.insert_after_marker in line:
                        insert_idx = i
                        break
                if insert_idx is None:
                    raise PatchError(
                        f"Marker not found in {patch.path}: "
                        f"{patch.insert_after_marker!r}"
                    )
            else:
                raise PatchError(
                    f"insert_before_line requires insert_after_marker or "
                    f"target_line for: {patch.path}"
                )

            content_to_insert = patch.content
            if not content_to_insert.endswith("\n"):
                content_to_insert += "\n"
            lines.insert(insert_idx, content_to_insert)
            target.write_text("".join(lines), encoding="utf-8")

        modified.append(target)
        console.print(f"[green]Patched:[/green] {patch.path} ({patch.action})")

    return modified
