# AutoFolio

Automatically add projects to your portfolio website using LLM-powered analysis. AutoFolio adapts to whatever portfolio structure you already have. No refactoring required. Safe, preview-first workflow.

## How It Works

1. Point AutoFolio at a project (repo URL, description, or interactive Q&A)
2. AutoFolio extracts structured metadata (title, description, tech stack, tags)
3. It scans your portfolio repo and detects the framework (Next.js, React/Vite, Hugo, Jekyll, Astro, static HTML)
4. An LLM analyzes the repo structure, decides where and how to add your project
5. AutoFolio generates the content and shows you a diff preview
6. If you approve, it applies the changes, verifies the build, pushes a branch, and opens a PR

## Requirements

- Python 3.10+
- For GitHub clone/push/PR: `GITHUB_TOKEN` environment variable

## Installation

```bash
pip install -e ".[dev]"
```

For the chat Web UI, install the optional `web` extra:

```bash
pip install -e ".[web]"
```

You can also run AutoFolio as a module:

```bash
python3 -m autofolio
```

## Quick Start

### The fast way: `autofolio add`

Pass a GitHub repo URL and your portfolio path. AutoFolio clones the repo, reads the README and dependencies, and builds a project config automatically:

```bash
autofolio add https://github.com/user/smart-thermostat \
  --portfolio-path ~/my-portfolio
```

Review the diff preview, then apply:

```bash
autofolio add https://github.com/user/smart-thermostat \
  --portfolio-path ~/my-portfolio --apply
```

### The manual way: `autofolio run`

If you already have a JSON config file:

```bash
autofolio run --config project.json --portfolio-path ~/my-portfolio
```

Apply changes after reviewing the preview:

```bash
autofolio run --config project.json --portfolio-path ~/my-portfolio --apply
```

## Subcommands

AutoFolio has two subcommands: `add` (smart ingest) and `run` (config-file based).

### `autofolio add`

Smart project ingest with three modes:

**1. Repo URL** (recommended): Give AutoFolio a GitHub URL and it extracts everything automatically from the README, package manifests, and GitHub API metadata.

```bash
autofolio add https://github.com/user/my-project \
  --portfolio-path ~/my-portfolio
```

You can combine a repo URL with a description for extra context:

```bash
autofolio add https://github.com/user/my-project \
  --describe "A real-time dashboard for IoT sensor data" \
  --portfolio-path ~/my-portfolio
```

**2. `--describe`**: Provide a natural-language description instead of a repo URL. The LLM extracts structured fields from your description.

```bash
autofolio add --describe "Built a React + Firebase app that tracks gym workouts \
  with real-time sync. Deployed on Vercel." \
  --portfolio-path ~/my-portfolio
```

**3. `--interactive`**: Enter a conversational prompt mode where AutoFolio asks you questions one at a time and builds the config from your answers.

```bash
autofolio add --interactive --portfolio-path ~/my-portfolio
```

After ingest, you review and confirm the extracted config before AutoFolio runs the full pipeline (detect, analyze, generate, preview/apply).

Additional `add` options:

```
--save-config PATH    Save the extracted config to a JSON file
```

### `autofolio run`

Run the pipeline from a pre-built JSON config file. Pass `--config` multiple times for batch mode:

```bash
autofolio run --config project.json --portfolio-path ~/my-portfolio
```

Example config file:

```json
{
  "title": "Smart Thermostat AI",
  "description": "ML-powered thermostat optimization system",
  "repo_url": "https://github.com/user/smart-thermostat",
  "demo_url": "",
  "tech_stack": ["Python", "React"],
  "tags": ["machine-learning", "iot"]
}
```

### Shared Options

Both `add` and `run` accept these options:

```
--portfolio-path PATH           Local path to the portfolio repo
--portfolio-url URL             GitHub URL of the portfolio repo (cloned to a temp dir)
--apply                         Apply changes (default is dry-run)
--pr                            Open a pull request after pushing (default: push only)
--resume-path PATH              Path to a resume file for style matching
--provider [ollama|openai]      LLM provider (default: ollama)
--skip-build                    Skip build verification step
--profile-readme-url URL        GitHub URL to the profile README repo
--profile-readme-path PATH      Local path to the profile README repo
--no-profile                    Skip profile README update
--update-skills                 Also update the skills/badges section if new tech is detected
--preview / --no-preview        Interactive diff preview before applying (default: on when using --apply)
```

## LLM Providers

| Provider | Setup | Notes |
|----------|-------|-------|
| Ollama (default) | Install Ollama, pull a model | No API key needed. Uses 7B-class models locally. |
| OpenAI | Set `OPENAI_API_KEY` env var | Uses gpt-4o-mini by default. |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `AUTOFOLIO_LLM_PROVIDER` | Set to `ollama` or `openai` |
| `AUTOFOLIO_OLLAMA_MODEL` | Override the default Ollama model |
| `AUTOFOLIO_OPENAI_MODEL` | Override the default OpenAI model |
| `OLLAMA_BASE_URL` | Custom Ollama server URL (default: `http://localhost:11434`) |
| `OPENAI_API_KEY` | Required for OpenAI provider |
| `GITHUB_TOKEN` | Required for pushing branches and creating PRs |

## Portfolio Repo Modes

**Local path**: Works directly in the directory. If a GitHub remote is detected, AutoFolio automatically pushes the branch and opens a PR.

```bash
autofolio add https://github.com/user/my-project \
  --portfolio-path ~/my-portfolio --apply
```

**GitHub URL**: Clones into a temp directory, pushes a branch back, and opens a PR.

```bash
autofolio add https://github.com/user/my-project \
  --portfolio-url https://github.com/user/portfolio --apply
```

To open a pull request after pushing, pass `--pr`.

## Resume Snippets

If the LLM determines your project is resume-worthy, AutoFolio generates a resume snippet.

- With `--resume-path`: reads your resume and matches its style
- Without: generates a plain-text bullet point

Snippets are saved to `~/.autofolio/resume_snippets.md`.

## Running Tests

```bash
pytest
```

## Web UI

A ChatGPT-style chat interface is available via [Chainlit](https://chainlit.io). Paste a GitHub URL or describe a project in natural language; the assistant extracts metadata, shows a config card for approval, runs the pipeline, and displays a diff preview with Apply or Discard.

You can say where your portfolio is in the same message (e.g. "Add https://github.com/user/project to my portfolio at ~/my-site" or "portfolio at ./portfolio") or reply with just a path or URL when asked. A default can also be set in the settings (gear icon).

Install and run:

```bash
pip install -e ".[web]"
chainlit run autofolio/web/app.py -w
```

Open http://localhost:8000. Optionally use the settings (gear icon) for **Portfolio path**, **Portfolio URL**, **LLM provider**, and **Apply changes** (dry-run by default). Starter suggestions appear on the welcome screen.

## Project Structure

```
autofolio/
  autofolio/
    __init__.py
    __main__.py     - Enables python -m autofolio
    cli.py          - CLI entry point (Click)
    config.py       - Pydantic models and config loading
    ingest.py       - Smart project ingest (repo, describe, interactive)
    detector.py     - Stack/framework detection
    llm.py          - Two-step LLM pipeline (analysis + generation)
    profile.py      - GitHub profile README updates
    patcher.py      - Patch application
    preview.py      - Unified diff preview and interactive patch selection
    validator.py    - Build verification
    git_ops.py      - Git branch, commit, push, PR operations
    web/
      app.py        - Chainlit chat UI
  .chainlit/
    config.toml     - Chainlit server and UI config
  chainlit.md      - Welcome message for the Web UI
  public/
    theme.json      - Teal/cyan theme (light and dark)
    stylesheet.css  - Custom CSS overrides
    avatars/        - Bot avatar
  tests/
    test_cli_integration.py
    test_detector.py
    test_ingest.py
    test_profile.py
    test_patcher.py
    test_validator.py
  pyproject.toml
  README.md
  MVP.md           - MVP plan and design notes
```

## License

MIT
