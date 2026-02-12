# AutoFolio Usage Guide

This guide covers prerequisites, installation, and how to use AutoFolio from the command line and the Web UI.

## Prerequisites

- **Python 3.10 or later.** Check with: `python3 --version`
- **Git.** Required for cloning repos, branching, and pushing. AutoFolio uses GitPython and GitHub APIs.
- **LLM access** (one of the following):
  - **Ollama** (default): Install [Ollama](https://ollama.com), then pull a model (e.g. `ollama pull qwen2.5-coder:7b`). No API key needed; runs locally.
  - **OpenAI**: Set the `OPENAI_API_KEY` environment variable. Uses gpt-4o-mini by default.
- **GitHub token** (for clone/push/PR): Set `GITHUB_TOKEN` if you use `--portfolio-url` or want AutoFolio to push branches and open pull requests. Create a token with `repo` scope at GitHub Settings > Developer settings > Personal access tokens.

## Installation

From the project root:

```bash
pip install -e ".[dev]"
```

This installs AutoFolio in editable mode with dev dependencies (e.g. pytest).

For the chat Web UI, install the optional `web` extra:

```bash
pip install -e ".[web]"
```

Verify the CLI:

```bash
autofolio --help
```

You can also run AutoFolio as a module:

```bash
python3 -m autofolio --help
```

## Command Line Usage

AutoFolio has two main subcommands: `add` (smart ingest from repo or description) and `run` (pipeline from a config file).

### Adding a project: `autofolio add`

**By GitHub repo URL (recommended)**

AutoFolio clones the repo, reads the README and dependency files, and builds a project config:

```bash
autofolio add https://github.com/user/smart-thermostat \
  --portfolio-path ~/my-portfolio
```

Optional extra context:

```bash
autofolio add https://github.com/user/my-project \
  --describe "A real-time dashboard for IoT sensor data" \
  --portfolio-path ~/my-portfolio
```

**By description only**

Give a short description; the LLM extracts title, tech stack, and tags:

```bash
autofolio add --describe "Built a React + Firebase app that tracks gym workouts with real-time sync. Deployed on Vercel." \
  --portfolio-path ~/my-portfolio
```

**Interactive mode**

Answer questions one at a time to build the config:

```bash
autofolio add --interactive --portfolio-path ~/my-portfolio
```

After ingest you review the config, then AutoFolio runs detection, analysis, generation, and shows a diff. To apply changes:

```bash
autofolio add https://github.com/user/smart-thermostat \
  --portfolio-path ~/my-portfolio --apply
```

Save the extracted config for later use:

```bash
autofolio add https://github.com/user/my-project \
  --portfolio-path ~/my-portfolio --save-config project.json
```

### Running from a config file: `autofolio run`

Use a pre-built JSON config:

```bash
autofolio run --config project.json --portfolio-path ~/my-portfolio
```

Apply after reviewing the preview:

```bash
autofolio run --config project.json --portfolio-path ~/my-portfolio --apply
```

Batch mode (multiple configs):

```bash
autofolio run --config project1.json --config project2.json --portfolio-path ~/my-portfolio
```

### Config file format

The JSON config must include at least `title`, `description`, and `repo_url`. Other fields are optional:

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

- `title`: Project name (required, non-empty).
- `description`: Short description (required, non-empty).
- `repo_url`: GitHub repository URL (required).
- `demo_url`: Live demo URL (optional, default `""`).
- `tech_stack`: List of technologies (optional).
- `tags`: List of tags for filtering or display (optional).

### Shared options (both `add` and `run`)

| Option | Description |
|--------|-------------|
| `--portfolio-path PATH` | Local path to the portfolio repo. |
| `--portfolio-url URL` | GitHub URL of the portfolio repo (cloned to a temp dir). |
| `--apply` | Apply changes. Default is dry-run (preview only). |
| `--pr` | Open a pull request after pushing (otherwise push only). |
| `--resume-path PATH` | Path to your resume file for style-matched resume snippets. |
| `--provider [ollama\|openai]` | LLM provider (default: ollama). |
| `--skip-build` | Skip build verification after applying patches. |
| `--profile-readme-url URL` | GitHub URL of the profile README repo. |
| `--profile-readme-path PATH` | Local path to the profile README repo. |
| `--no-profile` | Skip profile README update. |
| `--update-skills` | Update skills/badges section if new tech is detected. |
| `--preview` / `--no-preview` | Interactive diff preview before applying (default: on when using `--apply`). |

### Portfolio repo modes

- **Local path** (`--portfolio-path`): AutoFolio works in that directory on a new branch. If a GitHub remote is present, it can push and open a PR when you use `--apply` and optionally `--pr`.
- **GitHub URL** (`--portfolio-url`): AutoFolio clones the repo into a temp directory, applies changes, pushes a branch, and can open a PR. Requires `GITHUB_TOKEN`.

## LLM Providers and environment variables

| Variable | Purpose |
|----------|---------|
| `AUTOFOLIO_LLM_PROVIDER` | `ollama` or `openai`. |
| `AUTOFOLIO_OLLAMA_MODEL` | Override default Ollama model. |
| `AUTOFOLIO_OPENAI_MODEL` | Override default OpenAI model. |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`). |
| `OPENAI_API_KEY` | Required for OpenAI provider. |
| `GITHUB_TOKEN` | Required for pushing branches and creating PRs. |

## Resume snippets

If the LLM marks the project as resume-worthy, AutoFolio generates a resume bullet. With `--resume-path` it matches your resume style; otherwise it outputs plain text. Snippets are appended to `~/.autofolio/resume_snippets.md`.

## Web UI

A chat interface (Chainlit) lets you paste a GitHub URL or describe a project in natural language. The assistant extracts metadata, shows a config card for approval, runs the pipeline, and shows a diff with Apply or Discard.

Install and run:

```bash
pip install -e ".[web]"
chainlit run autofolio/web/app.py -w
```

Open http://localhost:8000. You can specify the portfolio in chat (e.g. "Add https://github.com/user/project to my portfolio at ~/my-site") or when prompted. Use the settings (gear icon) to set default **Portfolio path**, **Portfolio URL**, **LLM provider**, and **Apply changes** (default is dry-run).

## Running tests

From the project root:

```bash
pytest
```
