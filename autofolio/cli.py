from __future__ import annotations

import datetime
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from autofolio.config import load_project_config
from autofolio.detector import detect_stack
from autofolio.git_ops import (
    cleanup_temp,
    clone_repo,
    commit_changes,
    create_branch,
    create_pull_request,
    get_github_remote_url,
    push_branch,
)
from autofolio.llm import (
    generate_focused_entry,
    generate_resume_snippet,
    get_llm,
    read_requested_files,
    run_analysis,
    run_generation,
    validate_analysis,
    validate_generation,
)
from autofolio.patcher import apply_patches, preview_patches
from autofolio.profile import (
    discover_profile_repo,
    extract_github_username,
    run_profile_step,
)
from autofolio.validator import BuildError, run_build

console = Console()

RESUME_SNIPPETS_DIR = Path.home() / ".autofolio"
RESUME_SNIPPETS_FILE = RESUME_SNIPPETS_DIR / "resume_snippets.md"


def shared_pipeline_options(f):
    options = [
        click.option(
            "--portfolio-path",
            type=click.Path(exists=True),
            default=None,
            help="Local path to the portfolio repo.",
        ),
        click.option(
            "--portfolio-url",
            type=str,
            default=None,
            help="GitHub URL of the portfolio repo.",
        ),
        click.option(
            "--apply",
            "do_apply",
            is_flag=True,
            default=False,
            help="Apply changes. Without this flag, runs in dry-run mode.",
        ),
        click.option(
            "--no-pr",
            "skip_pr",
            is_flag=True,
            default=False,
            help="Skip automatic PR creation even if a GitHub remote is detected.",
        ),
        click.option(
            "--resume-path",
            type=click.Path(exists=True),
            default=None,
            help="Path to an existing resume file (LaTeX, Markdown, HTML, plain text, etc.).",
        ),
        click.option(
            "--provider",
            type=click.Choice(["ollama", "openai"]),
            default=None,
            help="LLM provider (default: ollama, or set AUTOFOLIO_LLM_PROVIDER).",
        ),
        click.option(
            "--skip-build",
            is_flag=True,
            default=False,
            help="Skip build verification step.",
        ),
        click.option(
            "--profile-readme-url",
            type=str,
            default=None,
            help="GitHub URL to the profile README repo (username/username).",
        ),
        click.option(
            "--profile-readme-path",
            type=click.Path(exists=True),
            default=None,
            help="Local path to the profile README repo.",
        ),
        click.option(
            "--no-profile",
            is_flag=True,
            default=False,
            help="Skip profile README update even if discoverable.",
        ),
        click.option(
            "--update-skills",
            is_flag=True,
            default=False,
            help="Also update the skills/badges section if new tech is detected.",
        ),
    ]
    for option in reversed(options):
        f = option(f)
    return f


@click.group()
def main():
    pass


@main.command()
@click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to the project JSON config file.",
)
@shared_pipeline_options
def run(
    config_path: str,
    portfolio_path: str | None,
    portfolio_url: str | None,
    do_apply: bool,
    skip_pr: bool,
    resume_path: str | None,
    provider: str | None,
    skip_build: bool,
    profile_readme_url: str | None,
    profile_readme_path: str | None,
    no_profile: bool,
    update_skills: bool,
) -> None:
    console.print(Panel("[bold]AutoFolio[/bold] - Portfolio Automation", style="cyan"))

    if not portfolio_path and not portfolio_url:
        console.print(
            "[red]Provide either --portfolio-path or --portfolio-url.[/red]"
        )
        sys.exit(1)

    if portfolio_path and portfolio_url:
        console.print(
            "[red]Provide only one of --portfolio-path or --portfolio-url.[/red]"
        )
        sys.exit(1)

    config_file = Path(config_path).resolve()
    project = load_project_config(config_path)
    console.print(f"[bold]Project:[/bold] {project.title}")
    console.print(f"[dim]{project.description}[/dim]")

    is_remote = portfolio_url is not None
    temp_dir: Path | None = None

    if is_remote:
        temp_dir = clone_repo(portfolio_url)
        repo_path = temp_dir
    else:
        repo_path = Path(portfolio_path).resolve()

    try:
        _run_pipeline(
            repo_path=repo_path,
            project=project,
            portfolio_url=portfolio_url,
            do_apply=do_apply,
            skip_pr=skip_pr,
            resume_path=resume_path,
            provider=provider,
            skip_build=skip_build,
            is_remote=is_remote,
            config_file=config_file,
            profile_readme_url=profile_readme_url,
            profile_readme_path=profile_readme_path,
            no_profile=no_profile,
            update_skills=update_skills,
        )
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)
    finally:
        if temp_dir:
            cleanup_temp(temp_dir)


@main.command()
@click.argument("repo", required=False, default=None)
@click.option(
    "--describe",
    type=str,
    default=None,
    help="Natural language project description.",
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    default=False,
    help="Enter conversational prompt mode.",
)
@click.option(
    "--save-config",
    type=click.Path(),
    default=None,
    help="Save the extracted config to a JSON file.",
)
@shared_pipeline_options
def add(
    repo: str | None,
    describe: str | None,
    interactive: bool,
    save_config: str | None,
    portfolio_path: str | None,
    portfolio_url: str | None,
    do_apply: bool,
    skip_pr: bool,
    resume_path: str | None,
    provider: str | None,
    skip_build: bool,
    profile_readme_url: str | None,
    profile_readme_path: str | None,
    no_profile: bool,
    update_skills: bool,
) -> None:
    console.print(Panel("[bold]AutoFolio[/bold] - Smart Project Ingest", style="cyan"))

    if not repo and not describe and not interactive:
        console.print(
            "[red]Provide at least one of: a repo URL/path, "
            "--describe, or --interactive.[/red]"
        )
        sys.exit(1)

    if not portfolio_path and not portfolio_url:
        console.print(
            "[red]Provide either --portfolio-path or --portfolio-url.[/red]"
        )
        sys.exit(1)

    if portfolio_path and portfolio_url:
        console.print(
            "[red]Provide only one of --portfolio-path or --portfolio-url.[/red]"
        )
        sys.exit(1)

    from autofolio.ingest import (
        confirm_config,
        ingest_from_description,
        ingest_from_repo,
        ingest_interactive,
        save_config_json,
    )

    llm = get_llm(provider)

    if interactive:
        project = ingest_interactive(llm)
    elif repo and describe:
        project = ingest_from_repo(llm, repo, extra_description=describe)
    elif repo:
        project = ingest_from_repo(llm, repo)
    else:
        project = ingest_from_description(llm, describe)

    project = confirm_config(project)
    if project is None:
        sys.exit(0)

    if save_config:
        save_config_json(project, save_config)

    console.print(f"\n[bold]Project:[/bold] {project.title}")
    console.print(f"[dim]{project.description}[/dim]")

    is_remote = portfolio_url is not None
    temp_dir: Path | None = None

    if is_remote:
        temp_dir = clone_repo(portfolio_url)
        repo_path = temp_dir
    else:
        repo_path = Path(portfolio_path).resolve()

    try:
        _run_pipeline(
            repo_path=repo_path,
            project=project,
            portfolio_url=portfolio_url,
            do_apply=do_apply,
            skip_pr=skip_pr,
            resume_path=resume_path,
            provider=provider,
            skip_build=skip_build,
            is_remote=is_remote,
            config_file=None,
            profile_readme_url=profile_readme_url,
            profile_readme_path=profile_readme_path,
            no_profile=no_profile,
            update_skills=update_skills,
        )
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)
    finally:
        if temp_dir:
            cleanup_temp(temp_dir)


def _run_pipeline(
    repo_path: Path,
    project,
    portfolio_url: str | None,
    do_apply: bool,
    skip_pr: bool,
    resume_path: str | None,
    provider: str | None,
    skip_build: bool,
    is_remote: bool,
    config_file: Path | None = None,
    profile_readme_url: str | None = None,
    profile_readme_path: str | None = None,
    no_profile: bool = False,
    update_skills: bool = False,
) -> None:
    console.print("\n[bold]Step 1: Detecting stack...[/bold]")
    detection = detect_stack(repo_path)
    console.print(f"  Stack: [cyan]{detection.stack}[/cyan]")
    console.print(f"  Package manager: [cyan]{detection.package_manager}[/cyan]")
    console.print(f"  Files: {len(detection.file_tree)}")
    console.print(f"  Key files: {list(detection.key_files.keys())}")
    if detection.build_commands:
        console.print(f"  Build: {' && '.join(detection.build_commands)}")
    if detection.project_listing:
        pl = detection.project_listing
        console.print(
            f"  Project listing: [cyan]{pl.file_path}[/cyan] "
            f"({pl.variable_name}, {pl.entry_count} entries)"
        )

    console.print("\n[bold]Step 2: Analyzing portfolio with LLM...[/bold]")
    llm = get_llm(provider)
    analysis = run_analysis(llm, project, detection)

    console.print(f"  Priority: [cyan]{analysis.evaluation.portfolio_priority}[/cyan]")
    console.print(f"  Resume-worthy: {'yes' if analysis.evaluation.resume_worthy else 'no'}")
    console.print(f"  Reason: {analysis.evaluation.reason}")

    console.print("\n  [dim]Validating analysis...[/dim]")
    analysis = validate_analysis(analysis, detection)
    console.print(f"  Files to read: {analysis.files_to_read}")
    for action in analysis.plan:
        console.print(f"  Plan: {action.action} {action.path} -- {action.explain}")

    console.print("\n[bold]Step 3: Generating patches with LLM...[/bold]")
    file_contents = read_requested_files(repo_path, analysis.files_to_read)
    generation = run_generation(llm, project, analysis, file_contents, detection)

    console.print(f"\n  [dim]Validating patches...[/dim]")
    generation = validate_generation(generation, file_contents, detection)
    console.print(f"  Valid patches: {len(generation.patch)}")

    if not generation.patch:
        console.print(
            "[yellow]  Main generation failed. "
            "Running focused entry generation...[/yellow]"
        )
        priority = analysis.evaluation.portfolio_priority
        focused = generate_focused_entry(llm, project, detection, priority)
        if focused:
            generation.patch = [focused]
            console.print(f"[green]  Focused generation succeeded.[/green]")
        else:
            console.print(
                "[bold red]No valid patches could be generated.[/bold red]"
            )
            return

    profile_patches = []
    profile_repo_path = None
    profile_temp_dir = None
    profile_is_remote = False

    if not no_profile:
        profile_result = _resolve_profile_repo(
            profile_readme_url, profile_readme_path, portfolio_url, repo_path
        )
        if profile_result:
            profile_repo_path, profile_temp_dir, profile_is_remote = profile_result
            console.print("\n[bold]Profile README step: generating entry...[/bold]")
            priority = analysis.evaluation.portfolio_priority
            try:
                profile_patches = run_profile_step(
                    llm, project, priority, profile_repo_path, update_skills
                )
                if profile_patches:
                    console.print(
                        f"[green]  Profile patches ready: "
                        f"{len(profile_patches)}[/green]"
                    )
                else:
                    console.print("[dim]  No profile patches generated.[/dim]")
            except Exception as e:
                console.print(
                    f"[yellow]Profile README step failed: {e}[/yellow]"
                )
                profile_patches = []

    if not do_apply:
        console.print("\n[bold yellow]DRY RUN (pass --apply to write changes)[/bold yellow]")
        console.print("\n[bold]Portfolio patches:[/bold]")
        preview_patches(repo_path, generation.patch)
        if profile_patches and profile_repo_path:
            console.print("\n[bold]Profile README patches:[/bold]")
            preview_patches(profile_repo_path, profile_patches)
        _handle_resume(
            llm, project, analysis, generation, resume_path, dry_run=True
        )
        if profile_temp_dir:
            cleanup_temp(profile_temp_dir)
        return

    console.print("\n[bold]Step 4: Creating branch...[/bold]")
    branch_name = create_branch(repo_path, project.title)

    console.print("\n[bold]Step 5: Applying patches...[/bold]")
    apply_patches(repo_path, generation.patch)

    if not skip_build:
        console.print("\n[bold]Step 6: Build verification...[/bold]")
        try:
            run_build(repo_path, detection.build_commands)
        except BuildError as e:
            console.print(f"[bold red]Build failed, reverting changes...[/bold red]")
            from git import Repo as GitRepo
            repo = GitRepo(str(repo_path))
            repo.git.checkout("--", ".")
            repo.git.clean("-fd")
            console.print("[yellow]Changes reverted.[/yellow]")
            if profile_temp_dir:
                cleanup_temp(profile_temp_dir)
            raise

    console.print("\n[bold]Step 7: Committing and pushing...[/bold]")
    commit_changes(repo_path, project.title)

    remote_url = portfolio_url
    if not remote_url:
        remote_url = get_github_remote_url(repo_path)
        if remote_url:
            console.print(f"  Detected GitHub remote: [cyan]{remote_url}[/cyan]")

    pushed = False
    if remote_url:
        push_branch(repo_path, branch_name)
        pushed = True
        if skip_pr:
            console.print(
                f"[dim]Skipping PR creation (--no-pr). "
                f"Branch '{branch_name}' pushed.[/dim]"
            )
        else:
            create_pull_request(remote_url, branch_name, project.title, repo_path)
    else:
        console.print(
            f"[dim]No GitHub remote detected. "
            f"Branch '{branch_name}' created locally. "
            f"Push it yourself when ready.[/dim]"
        )

    if profile_patches and profile_repo_path:
        try:
            _apply_profile_patches(
                profile_repo_path=profile_repo_path,
                profile_patches=profile_patches,
                project=project,
                profile_readme_url=profile_readme_url,
                skip_pr=skip_pr,
                profile_is_remote=profile_is_remote,
            )
        except Exception as e:
            console.print(
                f"[yellow]Profile README update failed: {e}[/yellow]"
            )
            console.print(
                "[dim]Portfolio changes were not affected.[/dim]"
            )
        finally:
            if profile_temp_dir:
                cleanup_temp(profile_temp_dir)
    elif profile_temp_dir:
        cleanup_temp(profile_temp_dir)

    _handle_resume(
        llm, project, analysis, generation, resume_path, dry_run=False
    )

    if pushed and config_file and config_file.exists():
        _cleanup_config(config_file)

    console.print("\n[bold green]Done.[/bold green]")


def _resolve_profile_repo(
    profile_readme_url: str | None,
    profile_readme_path: str | None,
    portfolio_url: str | None,
    repo_path: Path,
) -> tuple[Path, Path | None, bool] | None:
    if profile_readme_path:
        console.print(f"[dim]Using local profile repo: {profile_readme_path}[/dim]")
        return Path(profile_readme_path).resolve(), None, False

    if profile_readme_url:
        console.print(f"[dim]Cloning profile repo: {profile_readme_url}[/dim]")
        temp_dir = clone_repo(profile_readme_url)
        return temp_dir, temp_dir, True

    username = extract_github_username(portfolio_url, repo_path)
    if not username:
        console.print(
            "[dim]Cannot auto-discover profile repo: "
            "no GitHub remote found. Use --profile-readme-url "
            "or --profile-readme-path to specify it.[/dim]"
        )
        return None

    console.print(f"[dim]Auto-discovering profile repo for: {username}[/dim]")
    if not discover_profile_repo(username):
        console.print(
            f"[dim]Profile repo {username}/{username} not found. "
            f"Skipping profile README step.[/dim]"
        )
        return None

    profile_url = f"https://github.com/{username}/{username}"
    console.print(f"[dim]Found profile repo, cloning: {profile_url}[/dim]")
    temp_dir = clone_repo(profile_url)
    return temp_dir, temp_dir, True


def _apply_profile_patches(
    profile_repo_path: Path,
    profile_patches: list,
    project,
    profile_readme_url: str | None,
    skip_pr: bool,
    profile_is_remote: bool,
) -> None:
    console.print("\n[bold]Step 8: Applying profile README patches...[/bold]")
    branch_name = create_branch(profile_repo_path, f"profile-{project.title}")

    apply_patches(profile_repo_path, profile_patches)

    commit_changes(profile_repo_path, f"profile: {project.title}")

    profile_remote = profile_readme_url
    if not profile_remote:
        profile_remote = get_github_remote_url(profile_repo_path)
        if profile_remote:
            console.print(
                f"  Detected profile GitHub remote: [cyan]{profile_remote}[/cyan]"
            )

    if profile_remote:
        push_branch(profile_repo_path, branch_name)
        if skip_pr:
            console.print(
                f"[dim]Skipping profile PR creation (--no-pr). "
                f"Branch '{branch_name}' pushed.[/dim]"
            )
        else:
            create_pull_request(
                profile_remote,
                branch_name,
                f"profile: {project.title}",
                profile_repo_path,
            )
    else:
        console.print(
            f"[dim]No GitHub remote on profile repo. "
            f"Branch '{branch_name}' created locally. "
            f"Push it yourself when ready.[/dim]"
        )


def _cleanup_config(config_file: Path) -> None:
    try:
        config_file.unlink()
        console.print(
            f"[dim]Cleaned up config file: {config_file.name}[/dim]"
        )
    except OSError as e:
        console.print(
            f"[yellow]Could not remove config file {config_file.name}: {e}[/yellow]"
        )


def _handle_resume(
    llm,
    project,
    analysis,
    generation,
    resume_path: str | None,
    dry_run: bool,
) -> None:
    if not analysis.evaluation.resume_worthy:
        return

    console.print("\n[bold]Resume Snippet[/bold]")

    snippet = generation.resume_snippet
    if not snippet:
        resume_content = None
        if resume_path:
            resume_content = Path(resume_path).read_text(encoding="utf-8")
        snippet = generate_resume_snippet(llm, project, resume_content)

    if resume_path:
        console.print("[dim]Matched to your resume style.[/dim]")
    else:
        console.print(
            "[dim]Here is a snippet you can add to your resume.[/dim]"
        )

    console.print(Panel(snippet, title="Resume Snippet", style="green"))

    if not dry_run:
        _save_resume_snippet(project.title, snippet)


def _save_resume_snippet(title: str, snippet: str) -> None:
    RESUME_SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {title}\n_Added: {timestamp}_\n\n{snippet}\n"
    with open(RESUME_SNIPPETS_FILE, "a", encoding="utf-8") as f:
        f.write(entry)
    console.print(f"[dim]Saved to {RESUME_SNIPPETS_FILE}[/dim]")


if __name__ == "__main__":
    main()
