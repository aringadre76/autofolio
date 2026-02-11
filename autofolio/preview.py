from __future__ import annotations

import difflib
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from autofolio.config import PatchAction
from autofolio.patcher import _sanitize_path

console = Console()


def _simulate_patch(original: str, patch: PatchAction) -> str:
    if patch.action == "create":
        return patch.content

    if patch.action == "replace":
        return patch.content

    if patch.action == "append":
        return original + patch.content

    lines = original.splitlines(keepends=True)

    if patch.action == "insert_after_line":
        marker = patch.insert_after_marker or ""
        insert_idx = None
        for i, line in enumerate(lines):
            if marker in line:
                insert_idx = i + 1
        if insert_idx is not None:
            content = patch.content
            if not content.endswith("\n"):
                content += "\n"
            lines.insert(insert_idx, content)

    elif patch.action == "insert_before_line":
        insert_idx = None
        if patch.target_line is not None:
            insert_idx = patch.target_line - 1
            if insert_idx < 0 or insert_idx > len(lines):
                insert_idx = None
        elif patch.insert_after_marker:
            for i, line in enumerate(lines):
                if patch.insert_after_marker in line:
                    insert_idx = i
                    break
        if insert_idx is not None:
            content = patch.content
            if not content.endswith("\n"):
                content += "\n"
            lines.insert(insert_idx, content)

    return "".join(lines)


def _compute_diff(repo_root: Path, patch: PatchAction) -> str:
    target = _sanitize_path(repo_root, patch.path)

    if patch.action == "create":
        old_text = ""
    else:
        old_text = target.read_text(encoding="utf-8")

    new_text = _simulate_patch(old_text, patch)

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{patch.path}",
        tofile=f"b/{patch.path}",
        lineterm="",
    )
    return "\n".join(diff)


def _render_diff_panel(index: int, patch: PatchAction, diff_text: str) -> Panel:
    text = Text()
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            text.append(line + "\n", style="bold")
        elif line.startswith("@@"):
            text.append(line + "\n", style="cyan")
        elif line.startswith("+"):
            text.append(line + "\n", style="green")
        elif line.startswith("-"):
            text.append(line + "\n", style="red")
        else:
            text.append(line + "\n")

    title = f"[{index + 1}] {patch.path} ({patch.action})"
    return Panel(text, title=title, border_style="cyan", expand=True)


def show_patches(
    repo_root: Path,
    patches: list[PatchAction],
    label: str = "Patches",
) -> None:
    if not patches:
        console.print(f"[dim]No {label.lower()} to show.[/dim]")
        return

    console.print(f"\n[bold]{label} ({len(patches)} file(s)):[/bold]")

    for i, patch in enumerate(patches):
        try:
            diff_text = _compute_diff(repo_root, patch)
        except Exception as exc:
            diff_text = f"(could not compute diff: {exc})"

        if diff_text:
            panel = _render_diff_panel(i, patch, diff_text)
            console.print(panel)
        else:
            console.print(
                f"\n[bold cyan][{i + 1}] {patch.path} ({patch.action})[/bold cyan]"
            )
            console.print("[dim](no changes)[/dim]")


def preview_and_confirm(
    repo_root: Path,
    patches: list[PatchAction],
    label: str = "Patches",
) -> list[PatchAction]:
    if not patches:
        console.print(f"[dim]No {label.lower()} to preview.[/dim]")
        return []

    diffs: list[tuple[PatchAction, str]] = []
    for patch in patches:
        try:
            diff_text = _compute_diff(repo_root, patch)
        except Exception as exc:
            diff_text = f"(could not compute diff: {exc})"
        diffs.append((patch, diff_text))

    console.print(f"\n[bold]{label} ({len(patches)} file(s)):[/bold]")

    for i, (patch, diff_text) in enumerate(diffs):
        if diff_text:
            panel = _render_diff_panel(i, patch, diff_text)
            console.print(panel)
        else:
            console.print(
                f"\n[bold cyan][{i + 1}] {patch.path} ({patch.action})[/bold cyan]"
            )
            console.print("[dim](no changes)[/dim]")

    choice = Prompt.ask(
        "\nApply these changes?",
        choices=["y", "n", "select"],
        default="y",
    )

    if choice == "n":
        console.print("[yellow]Aborted. No changes applied.[/yellow]")
        return []

    if choice == "y":
        return patches

    return _select_patches(patches, diffs)


def _select_patches(
    patches: list[PatchAction],
    diffs: list[tuple[PatchAction, str]],
) -> list[PatchAction]:
    console.print(
        "\n[bold]Enter patch numbers to apply (comma-separated), or 'none':[/bold]"
    )
    for i, (patch, _) in enumerate(diffs):
        console.print(f"  [{i + 1}] {patch.path} ({patch.action})")

    raw = Prompt.ask("Patches to apply", default="none")
    if raw.strip().lower() == "none":
        console.print("[yellow]No patches selected.[/yellow]")
        return []

    selected: list[PatchAction] = []
    seen: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            idx = int(token) - 1
        except ValueError:
            console.print(f"[red]Ignoring invalid input: {token!r}[/red]")
            continue
        if idx in seen:
            continue
        seen.add(idx)
        if 0 <= idx < len(patches):
            selected.append(patches[idx])
        else:
            console.print(f"[red]Ignoring out-of-range: {token}[/red]")

    if selected:
        console.print(f"[green]Selected {len(selected)} patch(es).[/green]")
    else:
        console.print("[yellow]No valid patches selected.[/yellow]")
    return selected
