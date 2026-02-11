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
            Select(
                id="provider",
                label="LLM provider",
                values=["ollama", "openai"],
                initial_index=0,
            ),
            Switch(id="do_apply", label="Apply changes (write to repo)", initial=False),
            Switch(id="skip_build", label="Skip build verification", initial=False),
        ]
    ).send()
    cl.user_session.set("settings", {})
    llm = get_llm(None)
    cl.user_session.set("llm", llm)
    await cl.Message(
        content="Hi. I'm AutoFolio. Paste a GitHub repo URL or describe a project, and I'll add it to your portfolio. You can tell me where your portfolio is in the same message (e.g. \"Add https://github.com/user/project to my portfolio at ~/my-site\" or \"portfolio at ./portfolio\") or set a default in the settings (gear icon).",
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
    portfolio_path = (path_from_msg or settings.get("portfolio_path") or "").strip()
    portfolio_url = (url_from_msg or settings.get("portfolio_url") or "").strip()
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

    llm = cl.user_session.get("llm") or get_llm(settings.get("provider"))

    url_match = GITHUB_URL_RE.search(cleaned)
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


@cl.action_callback("edit_config")
async def on_edit_config(action: cl.Action):
    payload = action.payload or {}
    action_payload_base = payload
    config_dict = payload.get("config")
    if not config_dict:
        await cl.Message(content="No config to edit.", author="AutoFolio").send()
        return
    config = ProjectConfig(**config_dict)
    res = await cl.AskActionMessage(
        content="Which field do you want to change?",
        actions=[
            cl.Action(name="edit_title", payload={"value": "title"}, label="Title"),
            cl.Action(name="edit_description", payload={"value": "description"}, label="Description"),
            cl.Action(name="edit_repo_url", payload={"value": "repo_url"}, label="Repo URL"),
            cl.Action(name="edit_demo_url", payload={"value": "demo_url"}, label="Demo URL"),
            cl.Action(name="edit_tech_stack", payload={"value": "tech_stack"}, label="Tech stack"),
            cl.Action(name="edit_tags", payload={"value": "tags"}, label="Tags"),
            cl.Action(name="edit_done", payload={"value": "done"}, label="Done editing"),
        ],
    ).send()
    key = (res.get("payload") or {}).get("value") if res else None
    if not key or key == "done":
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
        await cl.Message(
            content=_config_to_markdown(config), actions=actions, author="AutoFolio"
        ).send()
        return
    if key == "tech_stack":
        new_val = await cl.AskUserMessage(content="Enter tech stack (comma-separated):", timeout=60)
        if new_val and new_val.get("output"):
            config.tech_stack = [x.strip() for x in new_val["output"].split(",") if x.strip()]
    elif key == "tags":
        new_val = await cl.AskUserMessage(content="Enter tags (comma-separated):", timeout=60)
        if new_val and new_val.get("output"):
            config.tags = [x.strip() for x in new_val["output"].split(",") if x.strip()]
    else:
        cur = getattr(config, key, "") or ""
        new_val = await cl.AskUserMessage(
            content=f"Current value: `{cur}`. Enter new value (or leave empty to keep):",
            timeout=60,
        )
        if new_val and (new_val.get("output") or "").strip():
            setattr(config, key, new_val["output"].strip())
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

    cl.user_session.set("pending_project", config_dict)
    cl.user_session.set("pending_patches", [p.model_dump() for p in patches])
    cl.user_session.set("repo_path", str(repo_path))
    cl.user_session.set("temp_dir", str(temp_dir) if temp_dir else None)
    cl.user_session.set("build_commands", detection.build_commands or [])
    cl.user_session.set("portfolio_url", portfolio_url or None)

    do_apply = settings.get("do_apply") is True
    actions = []
    if do_apply:
        actions.append(
            cl.Action(name="apply_patches", label="Apply changes", payload={})
        )
    actions.append(cl.Action(name="discard_patches", label="Discard", payload={}))

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
    cl.user_session.set("pending_project", None)
    cl.user_session.set("pending_patches", None)
    cl.user_session.set("repo_path", None)
    cl.user_session.set("temp_dir", None)
    cl.user_session.set("build_commands", None)
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

        await cl.Message(
            content=f"Done. Project **{project_title}** has been added to your portfolio.",
            author="AutoFolio",
        ).send()
    except Exception as e:
        await cl.Message(
            content=f"Error applying changes: {type(e).__name__}: {e}",
            author="AutoFolio",
        ).send()
    finally:
        if temp_dir_str:
            cleanup_temp(Path(temp_dir_str))
        cl.user_session.set("pending_project", None)
        cl.user_session.set("pending_patches", None)
        cl.user_session.set("repo_path", None)
        cl.user_session.set("temp_dir", None)
