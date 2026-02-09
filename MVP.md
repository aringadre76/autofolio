# AutoFolio MVP Plan (Phase 1)

## Goal

Take a new project's metadata and automatically add it to a user's portfolio website repo. Use an LLM to decide what content to generate and where to place it. AutoFolio adapts to whatever portfolio structure already exists. No refactoring required. Safe, preview-first workflow.

### Core Design Principle

AutoFolio never asks the user to restructure their portfolio site. Whether projects are hardcoded in a single TSX file, spread across markdown files, stored in YAML, or embedded in raw HTML, AutoFolio figures it out and works within the existing structure.

---

## 1. Project Input

- Single JSON config file passed via `--config project.json`
- Fields: `title`, `description`, `repo_url`, `demo_url`, `tech_stack`, `tags`
- Screenshots deferred to Phase 2 (no unused fields in the MVP)

Example:

```json
{
  "title": "Smart Thermostat AI",
  "description": "ML-powered thermostat optimization system",
  "repo_url": "https://github.com/arin/smart-thermostat",
  "demo_url": "",
  "tech_stack": ["Python", "React"],
  "tags": ["machine-learning", "iot"]
}
```

---

## 2. Portfolio Repo Input

Two ways the user can point AutoFolio at their portfolio site:

| Method | Flag | Notes |
|--------|------|-------|
| Local path | `--portfolio-path /local/path` | Works directly in that directory on a new branch |
| GitHub URL | `--portfolio-url https://github.com/user/repo` | Shallow clones into a temp directory, pushes branch back |

Auth:
- `GITHUB_TOKEN` env var is the standard auth mechanism.
- Required only for GitHub URL mode (clone + push).
- No over-engineered auth flow for the MVP.

Behavior:
- If a URL is given: shallow clone into a temp directory, work there, push branch back.
- If a local path is given: work in-place on a new branch.

---

## 3. Stack Detection

Scan the portfolio repo to detect the framework/tooling:

- Look for `package.json`, `config.toml`, `_config.yml`, `pyproject.toml`, `index.html`, etc.
- Classify as: Next.js, React/Vite, Hugo, Jekyll, Astro, plain static, or other.
- This tells the LLM what kind of content to generate (TSX/JSX objects, MDX, markdown, HTML, YAML entries, etc.)
- The detected stack also determines the build command used for verification (Section 7).

---

## 4. LLM Pipeline (Two-Step)

### LLM Provider

Configurable via `AUTOFOLIO_LLM_PROVIDER` env var:

| Provider | Value | Notes |
|----------|-------|-------|
| Ollama (local) | `ollama` (default) | Runs locally, no API key needed. Uses 7B-class models (e.g., Qwen 2.5 Coder 7B). Fits in 12GB VRAM. |
| OpenAI | `openai` | Requires `OPENAI_API_KEY` env var. Uses gpt-4o-mini or similar. |

Default is Ollama so the tool works out of the box with no API keys for anyone with a GPU.

LangChain abstracts the provider, so swapping is a config change, not a code change.

### Step 1 - Analysis

Send the LLM:
- The full repo file tree (all file paths, no contents yet)
- Detected stack info
- Project metadata from the config JSON

LLM returns a **plan**:
- Which file(s) it needs to read (requests specific files by path)
- Which file(s) to modify or create
- What action to take per file
- `portfolio_priority`: top / middle / bottom
- `resume_worthy`: true / false
- Reasoning

After Step 1, AutoFolio fetches the requested file contents and passes them to Step 2.

### Step 2 - Generation

Send the LLM:
- The plan from Step 1
- Full content of the target file(s) (the ones the LLM requested)
- Project metadata

LLM returns the **actual patch content** for each file.

This two-step approach means the LLM only sees the files it actually needs, and it separates the "what to do" decision from the "generate the content" work.

### Structured Output

Use **Pydantic models** to define and validate the LLM response schema.
Use LangChain's `.with_structured_output()` to enforce schema compliance.

Step 1 models (analysis, no content generation yet):

```python
from pydantic import BaseModel
from typing import Literal

class Evaluation(BaseModel):
    portfolio_priority: Literal["top", "middle", "bottom"]
    resume_worthy: bool
    reason: str

class PlannedAction(BaseModel):
    path: str
    action: Literal["create", "replace", "append", "insert_after_line"]
    explain: str

class AnalysisResponse(BaseModel):
    evaluation: Evaluation
    files_to_read: list[str]
    plan: list[PlannedAction]
```

Step 2 models (generation, includes content):

```python
class PatchAction(BaseModel):
    path: str
    action: Literal["create", "replace", "append", "insert_after_line"]
    insert_after_marker: str | None = None
    content: str

class GenerationResponse(BaseModel):
    patch: list[PatchAction]
    resume_snippet: str | None = None
```

---

## 5. Dry-Run and Preview

- **Default mode is `--dry-run`**: prints the plan, shows a diff preview, writes nothing.
- User must explicitly pass `--apply` to write changes.
- This is the most important trust and safety feature in the tool.

---

## 6. Patch Application

Supported actions:
- `create` - write a new file
- `replace` - overwrite an existing file
- `append` - add content to the end of a file
- `insert_after_line` - insert content after a specific marker line

Safety rules:
- **Path sanitization**: all patch paths must be relative and resolve within the repo root.
- **Action allow-list**: reject any action not in the supported set.
- **Fail loudly**: if a marker is not found during `insert_after_line`, raise an error instead of silently appending.
- **No restructuring**: AutoFolio only adds/modifies content. It never reorganizes existing files or suggests refactors.

---

## 7. Build Verification

- After applying the patch, run the detected build command:
  - React/Vite: `npm install && npm run build`
  - Next.js: `npm install && npm run build`
  - Hugo: `hugo --minify`
  - Jekyll: `bundle exec jekyll build`
  - Static HTML: no build step, skip
- If build **fails**: revert changes, print the error, exit non-zero.
- If build **passes** (or no build step applies): proceed to git operations.

---

## 8. Git Operations

- Create branch `auto/<project-slug>`
- Commit with a descriptive message
- **Default**: push the branch only
- `--pr` flag: also open a pull request via GitHub API
- If **local mode** without push: leave the branch for the user to review and push themselves

---

## 9. Resume Snippet

Two modes depending on whether the user provides a resume:

### With resume file (`--resume-path /path/to/resume.tex`)
- Assume LaTeX format.
- LLM reads the resume content, understands the existing style/format.
- LLM generates a snippet that matches the resume's structure.
- Snippet is output to stdout and appended to `~/.autofolio/resume_snippets.md`.

### Without resume file
- LLM still generates a resume-worthy snippet based on the project metadata.
- Output to stdout with a message: "Here is a snippet you can add to your resume (Overleaf, Google Docs, etc.)"
- Also appended to `~/.autofolio/resume_snippets.md`.

In both cases:
- Only triggered if the LLM marks the project as `resume_worthy` in Step 1.
- Entries in `resume_snippets.md` are timestamped and append-only.

---

## Project Structure

```
autofolio/
  autofolio/
    __init__.py
    cli.py
    config.py
    detector.py
    llm.py
    patcher.py
    validator.py
    git_ops.py
  tests/
    test_detector.py
    test_patcher.py
    test_validator.py
  pyproject.toml
  README.md
  MVP.md
```

---

## Key Decisions

| Decision | Answer |
|----------|--------|
| Portfolio input | Local path or GitHub URL (user provides) |
| No refactoring | AutoFolio adapts to whatever structure exists |
| LLM provider | Configurable: Ollama (local, default) or OpenAI |
| Local model | 7B-class (fits 12GB VRAM) |
| PR creation | Push-only default, `--pr` flag for PR |
| Resume with file | Assume LaTeX, generate matching snippet |
| Resume without file | Output generic snippet to stdout |
| Key file discovery | Full file tree in Step 1, LLM requests what it needs |
| File editing | Surgical insertion into existing files, no restructuring |

---

## Phase 2 (Future, Not MVP)

- Screenshot support (copy into repo assets, reference in generated content)
- GitHub profile README integration
- Swap LLM internals with RepoAgent/RepoMaster for multi-step reasoning
- Web UI or TUI for interactive preview
- Batch mode (add multiple projects at once)
- Template system (user defines their own patch templates per stack)
- Support for more LLM providers (Anthropic, local GGUF via llama.cpp, etc.)
