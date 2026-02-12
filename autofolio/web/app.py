from __future__ import annotations

import json
import re
from pathlib import Path

import chainlit as cl
from chainlit.input_widget import Select, Switch, TextInput

from autofolio.config import PatchAction, ProjectConfig
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
from autofolio.ingest import (
    GITHUB_URL_RE,
    fetch_github_metadata,
    ingest_from_description,
    ingest_from_repo,
)
from autofolio.llm import (
    generate_focused_entry,
    get_llm,
    read_requested_files,
    run_analysis,
    run_generation,
    validate_analysis,
    validate_generation,
)
from autofolio.patcher import apply_patches
from autofolio.preview import _compute_diff
from autofolio.profile import (
    detect_duplicate,
    discover_profile_repo,
    extract_github_username,
    project_already_in_portfolio,
    run_profile_step,
)
from autofolio.validator import BuildError, run_build

PORTFOLIO_PHRASE_RE = re.compile(
    r"(?:portfolio\s+(?:at|is|path\s+is?|:)\s*|(?:add\s+(?:this\s+)?)?to\s+(?:my\s+)?portfolio\s+(?:at\s+)?)\s*([^\s,]+)",
    re.IGNORECASE,
)
PORTFOLIO_AT_RE = re.compile(
    r"\b(?:portfolio\s+)?at\s+((?:/|~|\./|[A-Za-z]:)[^\s,]*)",
    re.IGNORECASE,
)
PATH_LIKE_RE = re.compile(
    r"(?:^|\s)((?:/|~|\./|[A-Za-z]:)[^\s,]*)",
)


def _looks_like_path(s: str) -> bool:
    s = s.strip()
    return bool(s and (s.startswith("~/") or s.startswith("./") or s.startswith("/") or (len(s) > 1 and s[1] == ":" and s[0].isalpha())))


def _parse_portfolio_from_message(text: str) -> tuple[str, str, str]:
    portfolio_path = ""
    portfolio_url = ""
    cleaned = text
    github_urls = list(GITHUB_URL_RE.finditer(text))
    
    if len(github_urls) >= 2:
        portfolio_url = github_urls[1].group(0)
        cleaned = cleaned.replace(portfolio_url, " ", 1)
    
    phrases_to_remove = []
    for m in PORTFOLIO_PHRASE_RE.finditer(text):
        val = m.group(1).strip().rstrip(".,;")
        phrase = m.group(0)
        phrases_to_remove.append(phrase)
        if GITHUB_URL_RE.match(val):
            if not portfolio_url:
                portfolio_url = val
        elif val and not portfolio_path:
            portfolio_path = val
    
    for phrase in phrases_to_remove:
        cleaned = cleaned.replace(phrase, " ", 1)
    
    if not portfolio_path:
        at_match = PORTFOLIO_AT_RE.search(text)
        if at_match and _looks_like_path(at_match.group(1)):
            portfolio_path = at_match.group(1).strip().rstrip(".,;")
            cleaned = cleaned.replace(at_match.group(0), " ", 1)
    if not portfolio_path and not portfolio_url and "portfolio" in text.lower():
        for path_match in PATH_LIKE_RE.finditer(text):
            cand = path_match.group(1).strip().rstrip(".,;")
            if _looks_like_path(cand) and not GITHUB_URL_RE.match(cand):
                portfolio_path = cand
                cleaned = cleaned.replace(path_match.group(0), " ", 1)
                break
    if not portfolio_path and not portfolio_url and _looks_like_path(text.strip()):
        portfolio_path = text.strip()
        cleaned = ""
    
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, portfolio_path, portfolio_url


def _config_to_markdown(config: ProjectConfig) -> str:
    lines = [
        "**Extracted project**",
        "",
        f"- **Title:** {config.title}",
        f"- **Description:** {config.description}",
        f"- **Repo URL:** " + (config.repo_url or "(none)"),
        f"- **Demo URL:** " + (config.demo_url or "(none)"),
        ("- **Tech stack:** " + ", ".join(config.tech_stack)) if config.tech_stack else "- **Tech stack:** (none)",
        ("- **Tags:** " + ", ".join(config.tags)) if config.tags else "- **Tags:** (none)",
    ]
    return "\n".join(lines)


def _collect_for_project_sync(repo_path: Path, project: ProjectConfig, llm, detection):
    analysis = run_analysis(llm, project, detection)
    analysis = validate_analysis(analysis, detection)
    file_contents = read_requested_files(repo_path, analysis.files_to_read)
    generation = run_generation(llm, project, analysis, file_contents, detection)
    generation = validate_generation(generation, file_contents, detection)
    if not generation.patch:
        priority = analysis.evaluation.portfolio_priority
        focused = generate_focused_entry(llm, project, detection, priority)
        if focused:
            generation.patch = [focused]
    return {
        "project": project,
        "patches": list(generation.patch),
        "analysis": analysis,
        "generation": generation,
    }


@cl.set_chat_profiles
async def chat_profile():
    return [
        cl.ChatProfile(
            name="default",
            markdown_description="Add projects to your portfolio through conversation.",
        ),
    ]


@cl.on_chat_start
async def on_chat_start():
    settings = await cl.ChatSettings(
        [
            TextInput(
                id="portfolio_path",
                label="Portfolio path",
                placeholder="/path/to/portfolio",
                initial="",
            ),
            TextInput(
                id="portfolio_url",
                label="Portfolio URL (alternative to path)",
                placeholder="https://github.com/user/portfolio",
                initial="",
            ),
            TextInput(
                id="profile_readme_path",
                label="Profile README path",
                placeholder="/path/to/username-repo",
                initial="",
            ),
            TextInput(
                id="profile_readme_url",
                label="Profile README URL (alternative to path)",
                placeholder="https://github.com/username/username",
                initial="",
            ),
            Select(
                id="provider",
                label="LLM provider",
                values=["ollama", "openai"],
                initial_index=0,
            ),
            Switch(id="do_apply", label="Apply changes (write to repo)", initial=False),
            Switch(id="skip_build", label="Skip build verification", initial=False),
            Switch(id="update_profile_readme", label="Update profile README", initial=False),
            Switch(id="update_skills", label="Update skills/badges in profile", initial=False),
        ]
    ).send()
    cl.user_session.set("settings", {})
    llm = get_llm(None)
    cl.user_session.set("llm", llm)
    await cl.Message(
        content="Hi. I'm AutoFolio. Paste a GitHub repo URL or describe a project, and I'll add it to your portfolio. Set **Portfolio path** in settings (gear icon), or say it in your message (e.g. \"Add this to my portfolio at ~/my-site\"). To also update your GitHub profile README, turn on **Update profile README** in settings and set **Profile README path** or URL.",
        author="AutoFolio",
    ).send()


@cl.on_settings_update
async def on_settings_update(settings: dict):
    cl.user_session.set("settings", settings)
    llm = get_llm(settings.get("provider"))
    cl.user_session.set("llm", llm)


@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="Add a project from GitHub",
            message="Add https://github.com/user/project to my portfolio",
            icon="github",
        ),
        cl.Starter(
            label="Describe a project",
            message="I built a React app that lets users bookmark places on a map. It uses Firebase and is deployed on Vercel.",
            icon="message-square",
        ),
        cl.Starter(
            label="Add multiple projects",
            message="I have two projects: https://github.com/me/app-one and https://github.com/me/app-two. Add both to my portfolio.",
            icon="layers",
        ),
        cl.Starter(
            label="Run from config file",
            message="I already have a project JSON config file. How do I add it using the CLI?",
            icon="file-json",
        ),
    ]


@cl.on_message
async def on_message(message: cl.Message):
    text = (message.content or "").strip()
    if not text:
        await cl.Message(content="Send a GitHub URL or a short description of your project. You can include where your portfolio is (e.g. \"portfolio at ~/my-site\").").send()
        return

    cleaned, path_from_msg, url_from_msg = _parse_portfolio_from_message(text)
    settings = cl.user_session.get("settings") or {}
    portfolio_path = (
        path_from_msg
        or cl.user_session.get("portfolio_path")
        or settings.get("portfolio_path")
        or ""
    ).strip()
    portfolio_url = (
        url_from_msg
        or cl.user_session.get("portfolio_url")
        or settings.get("portfolio_url")
        or ""
    ).strip()
    if not portfolio_path and not portfolio_url:
        await cl.Message(
            content="Where is your portfolio? Reply with a local path (e.g. `~/my-portfolio` or `./site`) or a GitHub repo URL (e.g. `https://github.com/me/me.github.io`). You can also set a default in the settings (gear icon)."
        ).send()
        return
    if portfolio_path and portfolio_url:
        await cl.Message(
            content="Give only one of portfolio path or portfolio URL, not both."
        ).send()
        return

    cl.user_session.set("portfolio_path", portfolio_path or None)
    cl.user_session.set("portfolio_url", portfolio_url or None)

    only_portfolio = not cleaned.strip() and (portfolio_path or portfolio_url)
    if only_portfolio:
        await cl.Message(
            content=f"Using portfolio: **{portfolio_path or portfolio_url}**. Now send the project: paste a GitHub repo URL or describe the project in a few words.",
            author="AutoFolio",
        ).send()
        return

    try:
        llm = cl.user_session.get("llm") or get_llm(settings.get("provider"))
    except (ValueError, EnvironmentError) as e:
        await cl.Message(
            content=f"LLM setup failed: {e}. Set **OPENAI_API_KEY** for OpenAI, or use Ollama (default).",
            author="AutoFolio",
        ).send()
        return

    url_match = GITHUB_URL_RE.search(cleaned)
    try:
        if url_match:
            repo_url = url_match.group(0)
            extra = cleaned.replace(repo_url, "").strip() or None
            async with cl.Step(name="Fetching GitHub metadata", type="tool") as step:
                meta = await cl.make_async(fetch_github_metadata)(repo_url)
                step.output = meta.get("name") or repo_url
            async with cl.Step(name="Cloning and extracting project metadata", type="tool") as step:
                config = await cl.make_async(ingest_from_repo)(llm, repo_url, extra_description=extra)
                step.output = config.title
        else:
            async with cl.Step(name="Extracting project metadata", type="tool") as step:
                config = await cl.make_async(ingest_from_description)(llm, cleaned)
                step.output = config.title
    except Exception as e:
        err_msg = str(e).lower()
        if "connection refused" in err_msg or "errno 111" in err_msg or "not reachable" in err_msg:
            await cl.Message(
                content=(
                    "**Project metadata extraction failed:** the LLM backend could not be reached (connection refused).\n\n"
                    "**To fix:**\n"
                    "- If you use **Ollama**, start it (e.g. run `ollama serve` in a terminal).\n"
                    "- Or open **Settings** (gear icon), set **LLM provider** to **OpenAI**, and set the `OPENAI_API_KEY` environment variable where the app runs."
                ),
                author="AutoFolio",
            ).send()
            return
        raise

    config_json = config.model_dump_json()
    action_payload = {
        "config": json.loads(config_json),
        "portfolio_path": portfolio_path or "",
        "portfolio_url": portfolio_url or "",
    }
    actions = [
        cl.Action(name="approve_config", label="Approve", payload=action_payload),
        cl.Action(name="edit_config", label="Edit", payload=action_payload),
        cl.Action(name="cancel_config", label="Cancel", payload={}),
    ]
    await cl.Message(
        content=_config_to_markdown(config),
        actions=actions,
        author="AutoFolio",
    ).send()


@cl.action_callback("cancel_config")
async def on_cancel_config(action: cl.Action):
    await cl.Message(content="Cancelled.", author="AutoFolio").send()
    cl.user_session.set("pending_project", None)
    cl.user_session.set("pending_patches", None)
    cl.user_session.set("repo_path", None)
    cl.user_session.set("temp_dir", None)
    cl.user_session.set("build_commands", None)


def _edit_field_actions(payload_base: dict) -> list:
    config_dict = payload_base.get("config") or {}
    return [
        cl.Action(name="edit_field", payload={**payload_base, "field": "title"}, label="Title"),
        cl.Action(name="edit_field", payload={**payload_base, "field": "description"}, label="Description"),
        cl.Action(name="edit_field", payload={**payload_base, "field": "repo_url"}, label="Repo URL"),
        cl.Action(name="edit_field", payload={**payload_base, "field": "demo_url"}, label="Demo URL"),
        cl.Action(name="edit_field", payload={**payload_base, "field": "tech_stack"}, label="Tech stack"),
        cl.Action(name="edit_field", payload={**payload_base, "field": "tags"}, label="Tags"),
        cl.Action(name="edit_field", payload={**payload_base, "field": "done"}, label="Done editing"),
    ]


@cl.action_callback("edit_config")
async def on_edit_config(action: cl.Action):
    payload = action.payload or {}
    action_payload_base = {
        "config": payload.get("config"),
        "portfolio_path": payload.get("portfolio_path", ""),
        "portfolio_url": payload.get("portfolio_url", ""),
    }
    config_dict = action_payload_base.get("config")
    if not config_dict:
        await cl.Message(content="No config to edit.", author="AutoFolio").send()
        return
    await cl.Message(
        content="Which field do you want to change?",
        actions=_edit_field_actions(action_payload_base),
        author="AutoFolio",
    ).send()


@cl.action_callback("edit_field")
async def on_edit_field(action: cl.Action):
    payload = action.payload or {}
    action_payload_base = {
        "config": payload.get("config"),
        "portfolio_path": payload.get("portfolio_path", ""),
        "portfolio_url": payload.get("portfolio_url", ""),
    }
    config_dict = action_payload_base.get("config")
    if not config_dict:
        await cl.Message(content="No config to edit.", author="AutoFolio").send()
        return
    field = payload.get("field")
    config = ProjectConfig(**config_dict)
    if field == "done" or not field:
        action_payload = action_payload_base
        actions = [
            cl.Action(name="approve_config", label="Approve", payload=action_payload),
            cl.Action(name="edit_config", label="Edit again", payload=action_payload),
            cl.Action(name="cancel_config", label="Cancel", payload={}),
        ]
        await cl.Message(
            content=_config_to_markdown(config), actions=actions, author="AutoFolio"
        ).send()
        return
    if field == "tech_stack":
        new_val = await cl.AskUserMessage(content="Enter tech stack (comma-separated):", timeout=60)
        if new_val and new_val.get("output"):
            config.tech_stack = [x.strip() for x in new_val["output"].split(",") if x.strip()]
    elif field == "tags":
        new_val = await cl.AskUserMessage(content="Enter tags (comma-separated):", timeout=60)
        if new_val and new_val.get("output"):
            config.tags = [x.strip() for x in new_val["output"].split(",") if x.strip()]
    else:
        cur = getattr(config, field, "") or ""
        new_val = await cl.AskUserMessage(
            content=f"Current value: `{cur}`. Enter new value (or leave empty to keep):",
            timeout=60,
        )
        if new_val and (new_val.get("output") or "").strip():
            setattr(config, field, new_val["output"].strip())
    config_dict = config.model_dump()
    action_payload = {
        "config": config_dict,
        "portfolio_path": action_payload_base.get("portfolio_path", ""),
        "portfolio_url": action_payload_base.get("portfolio_url", ""),
    }
    actions = [
        cl.Action(name="approve_config", label="Approve", payload=action_payload),
        cl.Action(name="edit_config", label="Edit again", payload=action_payload),
        cl.Action(name="cancel_config", label="Cancel", payload={}),
    ]
    await cl.Message(content=_config_to_markdown(config), actions=actions, author="AutoFolio").send()


def _payload_portfolio(payload: dict, settings: dict) -> tuple[str, str]:
    path = (payload.get("portfolio_path") or cl.user_session.get("portfolio_path") or settings.get("portfolio_path") or "").strip()
    url = (payload.get("portfolio_url") or cl.user_session.get("portfolio_url") or settings.get("portfolio_url") or "").strip()
    return path, url


def _resolve_profile_repo(
    profile_readme_url: str | None,
    profile_readme_path: str | None,
    portfolio_url: str | None,
    repo_path: Path,
) -> tuple[Path, Path | None, bool] | None:
    if profile_readme_path:
        p = Path(profile_readme_path).expanduser().resolve()
        if p.is_dir():
            return p, None, False
        return None
    if profile_readme_url:
        temp_dir = clone_repo(profile_readme_url)
        return temp_dir, temp_dir, True
    username = extract_github_username(portfolio_url, repo_path)
    if not username or not discover_profile_repo(username):
        return None
    profile_url = f"https://github.com/{username}/{username}"
    temp_dir = clone_repo(profile_url)
    return temp_dir, temp_dir, True


@cl.action_callback("approve_config")
async def on_approve_config(action: cl.Action):
    payload = action.payload or {}
    config_dict = payload.get("config")
    if not config_dict:
        await cl.Message(content="No config in payload.", author="AutoFolio").send()
        return
    config = ProjectConfig(**config_dict)
    settings = cl.user_session.get("settings") or {}
    portfolio_path, portfolio_url = _payload_portfolio(payload, settings)
    if not portfolio_path and not portfolio_url:
        await cl.Message(
            content="Set **Portfolio path** or **Portfolio URL** in settings first."
        ).send()
        return
    if portfolio_path and portfolio_url:
        await cl.Message(content="Set only one of path or URL.", author="AutoFolio").send()
        return

    llm = cl.user_session.get("llm") or get_llm(settings.get("provider"))
    temp_dir = None
    if portfolio_url:
        async with cl.Step(name="Cloning portfolio repo", type="tool") as step:
            temp_dir = await cl.make_async(clone_repo)(portfolio_url)
            repo_path = temp_dir
            step.output = "Cloned"
    else:
        repo_path = Path(portfolio_path).expanduser().resolve()
        if not repo_path.is_dir():
            await cl.Message(content=f"Portfolio path is not a directory: {repo_path}").send()
            return

    async with cl.Step(name="Detecting portfolio stack", type="tool") as step:
        detection = await cl.make_async(detect_stack)(repo_path)
        step.output = detection.stack or "unknown"

    if await cl.make_async(project_already_in_portfolio)(repo_path, config, detection):
        await cl.Message(
            content=f"**{config.title}** is already in your portfolio. No changes made.",
            author="AutoFolio",
        ).send()
        if temp_dir:
            cleanup_temp(temp_dir)
        return

    profile_readme_path_setting = (settings.get("profile_readme_path") or "").strip()
    if profile_readme_path_setting:
        profile_dir = Path(profile_readme_path_setting).expanduser().resolve()
        if profile_dir.is_dir():
            readme_path = profile_dir / "README.md"
            if readme_path.is_file():
                try:
                    profile_content = readme_path.read_text(encoding="utf-8")
                    if detect_duplicate(profile_content, config):
                        await cl.Message(
                            content=f"**{config.title}** is already in your profile README. No changes made.",
                            author="AutoFolio",
                        ).send()
                        if temp_dir:
                            cleanup_temp(temp_dir)
                        return
                except OSError:
                    pass

    async with cl.Step(name="Analyzing and generating patches", type="tool") as step:
        result = await cl.make_async(_collect_for_project_sync)(
            repo_path, config, llm, detection
        )
        step.output = f"{len(result['patches'])} patch(es)"

    patches = result["patches"]
    if not patches:
        await cl.Message(
            content="No valid patches could be generated for this project.",
            author="AutoFolio",
        ).send()
        if temp_dir:
            cleanup_temp(temp_dir)
        return

    diff_lines = []
    for i, patch in enumerate(patches):
        try:
            diff_text = _compute_diff(repo_path, patch)
        except Exception as e:
            diff_text = f"(could not compute diff: {e})"
        diff_lines.append(f"### [{i + 1}] {patch.path} ({patch.action})\n\n```diff\n{diff_text}\n```")
    diff_md = "\n\n".join(diff_lines)

    profile_repo_path = None
    profile_temp_dir = None
    profile_is_remote = False
    profile_readme_url_setting = (settings.get("profile_readme_url") or "").strip()
    profile_readme_path_setting = (settings.get("profile_readme_path") or "").strip()
    update_profile_readme = settings.get("update_profile_readme") is not False
    update_skills = settings.get("update_skills") is True
    profile_patches = []

    if update_profile_readme and (profile_readme_path_setting or profile_readme_url_setting or portfolio_url or get_github_remote_url(repo_path)):
        profile_result = _resolve_profile_repo(
            profile_readme_url_setting or None,
            profile_readme_path_setting or None,
            portfolio_url or None,
            repo_path,
        )
        if profile_result:
            profile_repo_path, profile_temp_dir, profile_is_remote = profile_result
            priority = result["analysis"].evaluation.portfolio_priority
            try:
                profile_patches = run_profile_step(
                    llm, config, priority, profile_repo_path, update_skills
                )
            except Exception:
                profile_patches = []
            if profile_patches:
                diff_lines.append("**Profile README**\n")
                for i, patch in enumerate(profile_patches):
                    try:
                        diff_text = _compute_diff(profile_repo_path, patch)
                    except Exception as e:
                        diff_text = f"(could not compute diff: {e})"
                    diff_lines.append(f"### Profile [{i + 1}] {patch.path} ({patch.action})\n\n```diff\n{diff_text}\n```")
                diff_md = "\n\n".join(diff_lines)

    cl.user_session.set("pending_project", config_dict)
    cl.user_session.set("pending_patches", [p.model_dump() for p in patches])
    cl.user_session.set("repo_path", str(repo_path))
    cl.user_session.set("temp_dir", str(temp_dir) if temp_dir else None)
    cl.user_session.set("build_commands", detection.build_commands or [])
    cl.user_session.set("portfolio_url", portfolio_url or None)
    cl.user_session.set("pending_profile_patches", [p.model_dump() for p in profile_patches])
    cl.user_session.set("profile_repo_path", str(profile_repo_path) if profile_repo_path else None)
    cl.user_session.set("profile_temp_dir", str(profile_temp_dir) if profile_temp_dir else None)
    cl.user_session.set("profile_is_remote", profile_is_remote)
    cl.user_session.set("profile_readme_url_setting", profile_readme_url_setting or None)

    actions = [
        cl.Action(name="apply_patches", label="Apply changes", payload={}),
        cl.Action(name="discard_patches", label="Discard", payload={}),
    ]

    await cl.Message(
        content="**Patch preview**\n\n" + diff_md,
        actions=actions,
        author="AutoFolio",
    ).send()


@cl.action_callback("discard_patches")
async def on_discard_patches(action: cl.Action):
    temp_dir = cl.user_session.get("temp_dir")
    if temp_dir:
        cleanup_temp(Path(temp_dir))
    profile_temp_dir = cl.user_session.get("profile_temp_dir")
    if profile_temp_dir:
        cleanup_temp(Path(profile_temp_dir))
    cl.user_session.set("pending_project", None)
    cl.user_session.set("pending_patches", None)
    cl.user_session.set("repo_path", None)
    cl.user_session.set("temp_dir", None)
    cl.user_session.set("build_commands", None)
    cl.user_session.set("pending_profile_patches", None)
    cl.user_session.set("profile_repo_path", None)
    cl.user_session.set("profile_temp_dir", None)
    cl.user_session.set("profile_is_remote", None)
    cl.user_session.set("profile_readme_url_setting", None)
    await cl.Message(content="Discarded. No changes applied.", author="AutoFolio").send()


@cl.action_callback("apply_patches")
async def on_apply_patches(action: cl.Action):
    repo_path_str = cl.user_session.get("repo_path")
    patches_dict = cl.user_session.get("pending_patches")
    build_commands = cl.user_session.get("build_commands") or []
    temp_dir_str = cl.user_session.get("temp_dir")
    portfolio_url = cl.user_session.get("portfolio_url")
    settings = cl.user_session.get("settings") or {}
    skip_build = settings.get("skip_build") is True

    if not repo_path_str or not patches_dict:
        await cl.Message(content="No pending patches to apply.", author="AutoFolio").send()
        return

    repo_path = Path(repo_path_str)
    patches = [PatchAction(**d) for d in patches_dict]
    config_dict = cl.user_session.get("pending_project") or {}
    project_title = config_dict.get("title", "Project")

    try:
        async with cl.Step(name="Creating branch", type="tool") as step:
            branch_name = await cl.make_async(create_branch)(repo_path, project_title)
            step.output = branch_name

        async with cl.Step(name="Applying patches", type="tool") as step:
            await cl.make_async(apply_patches)(repo_path, patches)
            step.output = f"{len(patches)} file(s)"

        if not skip_build and build_commands:
            async with cl.Step(name="Build verification", type="tool") as step:
                try:
                    await cl.make_async(run_build)(repo_path, build_commands)
                    step.output = "OK"
                except BuildError as e:
                    from git import Repo as GitRepo
                    repo = GitRepo(str(repo_path))
                    repo.git.checkout("--", ".")
                    repo.git.clean("-fd")
                    step.output = str(e)
                    await cl.Message(
                        content=f"Build failed. Changes reverted. {e}",
                        author="AutoFolio",
                    ).send()
                    if temp_dir_str:
                        cleanup_temp(Path(temp_dir_str))
                    cl.user_session.set("pending_project", None)
                    cl.user_session.set("pending_patches", None)
                    cl.user_session.set("repo_path", None)
                    cl.user_session.set("temp_dir", None)
                    return

        async with cl.Step(name="Committing and pushing", type="tool") as step:
            await cl.make_async(commit_changes)(repo_path, project_title)
            remote_url = portfolio_url or await cl.make_async(get_github_remote_url)(repo_path)
            if remote_url:
                await cl.make_async(push_branch)(repo_path, branch_name)
                await cl.make_async(create_pull_request)(
                    remote_url, branch_name, project_title, repo_path
                )
                step.output = "Pushed (PR created)"
            else:
                step.output = "Branch created locally (no remote)"

        profile_repo_path_str = cl.user_session.get("profile_repo_path")
        profile_patches_dict = cl.user_session.get("pending_profile_patches") or []
        profile_temp_dir_str = cl.user_session.get("profile_temp_dir")
        profile_readme_url_setting = cl.user_session.get("profile_readme_url_setting")

        if profile_repo_path_str and profile_patches_dict:
            profile_repo_path = Path(profile_repo_path_str)
            profile_patches = [PatchAction(**d) for d in profile_patches_dict]
            profile_label = f"profile-{project_title}"
            try:
                async with cl.Step(name="Profile README: creating branch", type="tool") as step:
                    profile_branch = await cl.make_async(create_branch)(profile_repo_path, profile_label)
                    step.output = profile_branch
                async with cl.Step(name="Profile README: applying patches", type="tool") as step:
                    await cl.make_async(apply_patches)(profile_repo_path, profile_patches)
                    step.output = f"{len(profile_patches)} file(s)"
                async with cl.Step(name="Profile README: committing and pushing", type="tool") as step:
                    await cl.make_async(commit_changes)(profile_repo_path, f"profile: {project_title}")
                    profile_remote = profile_readme_url_setting or await cl.make_async(get_github_remote_url)(profile_repo_path)
                    if profile_remote:
                        await cl.make_async(push_branch)(profile_repo_path, profile_branch)
                        await cl.make_async(create_pull_request)(
                            profile_remote, profile_branch, f"profile: {project_title}", profile_repo_path
                        )
                        step.output = "Pushed (PR created)"
                    else:
                        step.output = "Branch created locally (no remote)"
                done_msg = f"Done. Project **{project_title}** has been added to your portfolio and profile README."
            except Exception as profile_err:
                done_msg = f"Portfolio updated. Profile README update failed: {profile_err}"
            if profile_temp_dir_str:
                cleanup_temp(Path(profile_temp_dir_str))
        else:
            done_msg = f"Done. Project **{project_title}** has been added to your portfolio."

        await cl.Message(content=done_msg, author="AutoFolio").send()
    except Exception as e:
        await cl.Message(
            content=f"Error applying changes: {type(e).__name__}: {e}",
            author="AutoFolio",
        ).send()
    finally:
        if temp_dir_str:
            cleanup_temp(Path(temp_dir_str))
        profile_temp_dir_str = cl.user_session.get("profile_temp_dir")
        if profile_temp_dir_str:
            cleanup_temp(Path(profile_temp_dir_str))
        cl.user_session.set("pending_project", None)
        cl.user_session.set("pending_patches", None)
        cl.user_session.set("repo_path", None)
        cl.user_session.set("temp_dir", None)
        cl.user_session.set("pending_profile_patches", None)
        cl.user_session.set("profile_repo_path", None)
        cl.user_session.set("profile_temp_dir", None)
        cl.user_session.set("profile_is_remote", None)
        cl.user_session.set("profile_readme_url_setting", None)
