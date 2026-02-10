from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

console = Console()


class BuildError(Exception):
    pass


def run_build(repo_path: Path, build_commands: list[str]) -> bool:
    if not build_commands:
        console.print("[dim]No build step for this stack, skipping verification.[/dim]")
        return True

    repo_path = repo_path.resolve()
    console.print(f"[bold]Running build verification in {repo_path}...[/bold]")

    for cmd in build_commands:
        console.print(f"[dim]$ {cmd}[/dim]")
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            console.print(f"[bold red]Build failed:[/bold red] {cmd}")
            if result.stdout.strip():
                console.print(f"[dim]stdout:[/dim]\n{result.stdout[-2000:]}")
            if result.stderr.strip():
                console.print(f"[dim]stderr:[/dim]\n{result.stderr[-2000:]}")
            raise BuildError(
                f"Build command failed (exit {result.returncode}): {cmd}"
            )
        console.print(f"[green]OK[/green]")

    console.print("[bold green]Build verification passed.[/bold green]")
    return True
