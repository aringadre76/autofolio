# AutoFolio

Automatically add projects to your portfolio website using LLM-powered analysis. AutoFolio adapts to whatever portfolio structure you already have. No refactoring required. Safe, preview-first workflow.

## How It Works

1. You provide a JSON file describing your project (title, description, tech stack, etc.)
2. AutoFolio scans your portfolio repo and detects the framework (Next.js, React/Vite, Hugo, Jekyll, Astro, static HTML)
3. An LLM analyzes the repo structure, decides where and how to add your project
4. AutoFolio generates the content and shows you a diff preview
5. If you approve, it applies the changes, verifies the build, pushes a branch, and opens a PR

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Create a project config file

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

### 2. Run AutoFolio (dry-run by default)

```bash
autofolio --config project.json --portfolio-path /path/to/portfolio
```

### 3. Review the preview, then apply

```bash
autofolio --config project.json --portfolio-path /path/to/portfolio --apply
```

## Usage

```
autofolio --config <project.json> [OPTIONS]

Options:
  --portfolio-path PATH   Local path to the portfolio repo
  --portfolio-url URL     GitHub URL of the portfolio repo
  --apply                 Apply changes (default is dry-run)
  --no-pr                 Skip automatic PR creation
  --resume-path PATH      Path to a LaTeX resume file (for style matching)
  --provider [ollama|openai]  LLM provider (default: ollama)
  --skip-build            Skip build verification
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
autofolio --config project.json --portfolio-path ~/my-portfolio --apply
```

**GitHub URL**: Clones into a temp directory, pushes a branch back, and opens a PR.

```bash
autofolio --config project.json --portfolio-url https://github.com/user/portfolio --apply
```

To push the branch without opening a PR, pass `--no-pr`.

## Resume Snippets

If the LLM determines your project is resume-worthy, AutoFolio generates a resume snippet.

- With `--resume-path`: reads your LaTeX resume and matches its style
- Without: generates a plain-text bullet point

Snippets are saved to `~/.autofolio/resume_snippets.md`.

## Running Tests

```bash
pytest
```

## Project Structure

```
autofolio/
  autofolio/
    __init__.py
    cli.py          - CLI entry point (Click)
    config.py       - Pydantic models and config loading
    detector.py     - Stack/framework detection
    llm.py          - Two-step LLM pipeline (analysis + generation)
    patcher.py      - Patch preview and application
    validator.py    - Build verification
    git_ops.py      - Git branch, commit, push, PR operations
  tests/
    test_detector.py
    test_patcher.py
    test_validator.py
  pyproject.toml
  README.md
  MVP.md
```

## License

MIT
