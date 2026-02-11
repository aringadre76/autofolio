# AutoFolio MVP Plan (Phase 1)

## Goal

Take a new project's metadata and automatically add it to a user's portfolio website repo. Use an LLM to decide what content to generate and where to place it. AutoFolio adapts to whatever portfolio structure already exists. No refactoring required. Safe, preview-first workflow.

### Core Design Principle

AutoFolio never asks the user to restructure their portfolio site. Whether projects are hardcoded in a single TSX file, spread across markdown files, stored in YAML, or embedded in raw HTML, AutoFolio figures it out and works within the existing structure.

---

## 1. Project Input

- Single JSON config file passed via `--config project.json`
- Fields: `title`, `description`, `repo_url`, `demo_url`, `tech_stack`, `tags`
- Screenshots deferred to future backlog (no unused fields in the MVP)

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

## Phase 2 Backlog (Future, Not in Phase 1 or 2)

- Screenshot support (copy into repo assets, reference in generated content)
- Swap LLM internals with RepoAgent/RepoMaster for multi-step reasoning
- Web UI or TUI for interactive preview
- Batch mode (add multiple projects at once)
- Template system (user defines their own patch templates per stack)
- Support for more LLM providers (Anthropic, local GGUF via llama.cpp, etc.)

---

# AutoFolio Phase 2: GitHub Profile README Integration

## Goal

Extend AutoFolio to also update the user's GitHub profile README (`username/username` repo) when adding a new project. The profile README gets a condensed project entry that matches the existing style, placed according to the same priority logic used for the portfolio site. This runs as an additional step in the existing pipeline, not a replacement.

### Core Design Principle

Same as Phase 1: never restructure what already exists. Profile READMEs vary wildly (tables, badge grids, HTML cards, bullet lists, accordion sections, raw markdown). AutoFolio detects the pattern and works within it.

---

## 1. Profile README Discovery

AutoFolio needs to find and access the user's `username/username` repo.

Two ways the user can explicitly point AutoFolio at their profile repo (mirrors Phase 1's portfolio input pattern):

| Method | Flag | Notes |
|--------|------|-------|
| Local path | `--profile-readme-path /local/path` | Works directly in that directory on a new branch |
| GitHub URL | `--profile-readme-url https://github.com/user/user` | Shallow clones into a temp directory, pushes branch back |

### Auto-discovery (fallback)

If neither explicit flag is provided, AutoFolio attempts automatic discovery:

1. Extract the GitHub username from `--portfolio-url` or from the portfolio repo's GitHub remote.
2. If the portfolio is local with no GitHub remote, skip auto-discovery and print: "Cannot auto-discover profile repo: no GitHub remote found. Use --profile-readme-url or --profile-readme-path to specify it."
3. Check if `username/username` repo exists via the GitHub API (`gh api repos/{owner}/{owner}` or PyGithub).
4. If it exists, clone/open it. If not, skip profile README step with a message.

Priority: The explicit flags (`--profile-readme-url`, `--profile-readme-path`) take precedence. Auto-discovery is the fallback when neither is provided.

---

## 2. Profile README Parsing

The profile README is always a single file: `README.md` at the repo root. The challenge is understanding its structure.

### Section Detection

Scan the README for project-related sections. Common patterns:

| Pattern | Example |
|---------|---------|
| Markdown heading | `## Projects`, `## Featured Work`, `### What I've Built` |
| HTML comment markers | `<!-- PROJECTS:START -->` ... `<!-- PROJECTS:END -->` |
| Table header | `\| Project \| Description \| Tech \|` |
| Badge/shield rows | `[![Project](https://img.shields.io/...)]` |
| HTML card blocks | `<a href="..."><img ...></a>` with `<table>` or `<div>` layout |
| Bullet/numbered list | `- **Project Name** - description` |

Detection approach:
1. Split the README into sections by headings (`#`, `##`, `###`).
2. Score each section for "project-likeness": look for GitHub URLs, tech keywords, repo links, description patterns.
3. Pick the highest-scoring section as the project listing section.
4. If no section scores above threshold, fall back to appending a new `## Projects` section before the first non-header section.

### Format Detection

Once the project section is found, detect the listing format:

| Format | Detected By | Entry Template |
|--------|-------------|----------------|
| `table` | Markdown table syntax (`\|...\|...\|`) | New table row matching column structure |
| `bullet_list` | Lines starting with `- ` or `* ` containing bold project names | `- **Title** - description [link]` |
| `badge_grid` | `[![...](https://img.shields.io/...)]` patterns | New badge in same style |
| `html_cards` | `<a>`, `<img>`, `<table>`, `<div>` blocks with repo links | New HTML block matching structure |
| `heading_blocks` | Sub-headings per project (`### Project Name`) with body text | New heading block |
| `plain` | Freeform text paragraphs mentioning projects | Append a markdown block |

Store the detected format along with a sample entry. This mirrors the approach used in Phase 1 for portfolio sites (detect format, extract a sample, record positions), but adapted for markdown structures instead of code-level AST patterns.

### New Data Model

```python
class ProfileReadmeHint(BaseModel):
    section_heading: str
    section_start_line: int
    section_end_line: int
    format: Literal[
        "table", "bullet_list", "badge_grid",
        "html_cards", "heading_blocks", "plain"
    ]
    sample_entry: str
    entry_positions: list[int]
```

---

## 3. Profile Entry Generation

### LLM Prompt

The LLM receives:
- The detected format and a sample entry from the profile README.
- The project metadata (same `ProjectConfig` as Phase 1).
- Instruction to generate ONE entry in the exact same format.

This mirrors the `generate_focused_entry` pattern from Phase 1. The LLM only handles content generation; the code handles structural decisions (where to insert, indentation, format compliance).

### Format-Specific Generation

For each format, the focused generator produces different output:

**Table**: a new `| col1 | col2 | ... |` row matching the existing column count and alignment.

**Bullet list**: a new `- **Title** - description` line (or whatever the existing bullet style is).

**Badge grid**: a new `[![Title](badge_url)](repo_url)` badge. The badge URL is constructed from the project metadata (title, tech, color) using shields.io patterns detected from existing badges.

**HTML cards**: a new HTML block cloned from the sample entry with fields swapped.

**Heading blocks**: a new `### Title\n\ndescription\n\n[Repo](url)` block.

**Plain**: a new paragraph in the style of existing project mentions.

### Validation

Same validation pattern as Phase 1, plus format-specific checks for markdown:
- **Table rows**: verify column count matches the existing table header. Reject rows with mismatched pipe counts.
- **HTML cards**: verify all opened HTML tags are properly closed. Use a lightweight tag-balance check (not a full parser).
- **Badge grid**: verify the badge URL is well-formed and the markdown image/link syntax is complete.
- **All formats**: verify the generated entry is non-empty and does not contain obvious LLM artifacts (e.g., triple backticks, preamble text).
- If the LLM output fails validation, fall back to a code-constructed entry using the sample as a template with field substitution.

---

## 4. Priority-Based Placement

Reuse the `portfolio_priority` from the Phase 1 analysis step (already computed, no extra LLM call).

| Priority | Table | Bullet List | Other Formats |
|----------|-------|-------------|---------------|
| `top` | Insert as first data row (after header) | Insert as first bullet | Insert after section heading |
| `middle` | Insert at midpoint of rows | Insert at midpoint | Insert at midpoint of entries |
| `bottom` | Insert as last row (before any closing) | Insert as last bullet | Insert before section end |

Entry positions are tracked by scanning for each entry's start line within the project section (stored in `ProfileReadmeHint.entry_positions`), using the same line-number-based approach as Phase 1's portfolio patcher but adapted for markdown structures instead of JS/TS arrays.

---

## 5. Skills/Tech Badge Updates (Optional)

Many profile READMEs have a "Skills" or "Tech Stack" section with badge images, e.g.:

```markdown
![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?style=flat&logo=react&logoColor=black)
```

If AutoFolio detects a badge-based skills section AND the new project introduces tech not already listed, it can:
1. Identify which tech from `project.tech_stack` is missing from the skills section.
2. Generate matching badge URLs using the same `style=` parameter as existing badges.
3. Append the new badges to the skills section.

This is opt-in via `--update-skills` flag. Disabled by default to avoid unwanted profile changes.

---

## 6. CLI Changes

New flags:

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--profile-readme-url` | string | None | GitHub URL to the profile README repo |
| `--profile-readme-path` | path | None | Local path to the profile README repo |
| `--no-profile` | flag | False | Skip profile README update even if discoverable |
| `--update-skills` | flag | False | Also update the skills/badges section if new tech is detected |

Behavior:
- If `--profile-readme-url` or `--profile-readme-path` is provided, use that.
- Otherwise, attempt auto-discovery from the GitHub username (requires a GitHub remote on the portfolio repo).
- If auto-discovery fails or `--no-profile` is set, skip the profile step entirely.
- The profile README update respects `--dry-run` / `--apply` the same way as the portfolio step. In dry-run mode, the profile diff is printed alongside the portfolio diff. No changes are written to either repo unless `--apply` is passed.
- The profile README update happens AFTER the portfolio site update succeeds.
- Profile changes go on their own branch (`auto/profile-<project-slug>`) in the profile repo.
- A separate PR is opened for the profile repo (if applicable).

---

## 7. Pipeline Flow (Updated)

```
1. Load project config
2. Detect portfolio stack
3. LLM Analysis (portfolio priority, resume-worthiness)
4. LLM Generation (portfolio patches)
5. --- Profile README step (generation only, no writes yet) ---
   a. Discover/open profile README repo
   b. Parse README.md structure and detect project section + format
   c. Generate profile entry (LLM or code-constructed fallback)
   d. Validate generated entry (column count, HTML tag balance, format compliance)
   e. Compute insertion point from priority
   f. (Optional) Generate skills badge updates if --update-skills is set
6. Dry-run checkpoint: if --dry-run, print diffs for both portfolio and profile, then exit
7. Apply portfolio patches
8. Build verification (portfolio)
9. Commit + push + PR (portfolio)
10. Apply profile README patch (entry + skills badges)
11. Commit + push + PR (profile repo)
12. Resume snippet generation
13. Done
```

Step 5 is skipped entirely if no profile repo is found or `--no-profile` is set. The portfolio and profile repos are independent: a failure in the profile step (steps 10-11) does not revert the portfolio changes (steps 7-9). In `--dry-run` mode, both diffs (portfolio and profile) are printed together at step 6 and nothing is written to either repo.

---

## 8. New Modules

### `autofolio/profile.py`

Handles all profile README logic:
- `discover_profile_repo(github_username)` - check if `username/username` exists
- `parse_profile_readme(content)` - returns `ProfileReadmeHint`
- `detect_project_section(sections)` - scores sections for project-likeness
- `detect_entry_format(section_text)` - classifies format type
- `extract_sample_entry(section_text, format)` - pulls one entry as template
- `find_entry_positions(section_text, format)` - maps all entry line numbers
- `generate_profile_entry(llm, project, hint)` - LLM generation with fallback
- `validate_profile_entry(entry, hint)` - format-specific validation (column count, tag balance, artifact detection)
- `construct_entry_from_template(project, sample, format)` - code-only fallback

### `tests/test_profile.py`

Unit tests covering:
- Section detection across different README styles
- Format classification for tables, bullets, badges, HTML cards, heading blocks
- Entry generation and template substitution
- Entry validation (table column count, HTML tag balance, badge syntax, LLM artifact rejection)
- Priority-based insertion point calculation
- Skills badge detection and update logic

---

## 9. Edge Cases

| Scenario | Behavior |
|----------|----------|
| No profile repo exists | Print info message, skip profile step |
| README.md is empty | Create a minimal structure: `# Hi, I'm {username}\n\n## Projects\n\n` |
| No project section found | Append a new `## Projects` section |
| Project already listed (duplicate) | Detect by `repo_url` match first, then fall back to title match. Skip with warning if either matches. |
| README has mixed formats (table + bullets) | Use the highest-scoring project section (by project-likeness score from Section 2) |
| Profile repo has no GitHub remote | Commit locally, skip push/PR |
| Rate limits on GitHub API | Graceful degradation with retry + backoff |

---

## 10. Key Decisions

| Decision | Answer |
|----------|--------|
| Profile repo discovery | Auto-discover from GitHub username, explicit override available |
| README is always markdown | No stack detection needed, parse markdown directly |
| Entry format | Match whatever exists (table, bullets, badges, HTML, headings) |
| Priority reuse | Same `portfolio_priority` from Phase 1 analysis, no extra LLM call |
| Skills update | Opt-in only (`--update-skills`), disabled by default |
| Failure isolation | Profile failure does not revert portfolio changes |
| Separate PRs | Profile repo gets its own branch and PR |
| Duplicate detection | Match on `repo_url` first, fall back to title. Skip if either matches. |

---

## 11. Project Structure (Updated)

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
    profile.py          # Profile README parsing + generation
    ingest.py           # Smart project metadata extraction
  tests/
    test_detector.py
    test_patcher.py
    test_validator.py
    test_profile.py
    test_ingest.py      # Ingest module tests
  pyproject.toml
  README.md
  MVP.md
```

---

# AutoFolio Phase 3: Smart Project Ingest

## Goal

Let users provide project information naturally instead of hand-writing JSON config files. Accept a repo URL, a natural language description, or an interactive conversational prompt. An LLM extracts structured `ProjectConfig` metadata from whatever the user provides.

### Core Design Principle

Meet the user where they are. If they have a repo, point at it. If they want to describe a project in their own words, let them. The tool figures out the structured data, shows it for confirmation, and proceeds into the existing pipeline.

---

## 1. CLI Refactor

The CLI is converted from a single `@click.command()` to a `@click.group()` with two subcommands:

| Subcommand | Purpose |
|------------|---------|
| `autofolio run` | Existing behavior. Takes `--config project.json` and runs the pipeline. |
| `autofolio add` | Smart ingest. Accepts a repo URL, `--describe`, or `--interactive`. Extracts metadata, confirms with the user, then runs the same pipeline. |

Both subcommands share the same portfolio/profile flags via a `shared_pipeline_options` decorator (--portfolio-path, --portfolio-url, --apply, --pr, --resume-path, --provider, --skip-build, --profile-readme-url, --profile-readme-path, --no-profile, --update-skills).

The entry point in `pyproject.toml` remains `autofolio = "autofolio.cli:main"` since `main` is now the click group.

### `autofolio run` usage

```
autofolio run --config project.json --portfolio-path ./my-site
autofolio run --config project.json --portfolio-url https://github.com/user/site --apply
```

### `autofolio add` usage

```
autofolio add https://github.com/user/project --portfolio-path ./site
autofolio add --describe "PinPlace is a collaborative mapping app using React and Firebase"
autofolio add --interactive --portfolio-path ./site
autofolio add https://github.com/user/project --describe "extra context" --portfolio-url https://github.com/user/site
autofolio add https://github.com/user/project --save-config extracted.json --portfolio-path ./site
```

### `autofolio add` options

| Option | Type | Description |
|--------|------|-------------|
| `repo` (positional) | string (optional) | GitHub URL or local path to the project repo |
| `--describe` | string | Natural language project description |
| `--interactive` / `-i` | flag | Enter conversational prompt mode |
| `--save-config` | path | Save the extracted config to a JSON file |
| (shared options) | | All portfolio/profile flags from `run` except `--config` |

At least one of `repo`, `--describe`, or `--interactive` must be provided. Multiple inputs can be combined (e.g. repo URL + describe text both feed into the LLM context).

---

## 2. Ingest Module (`autofolio/ingest.py`)

### Data Sources

When a GitHub URL is provided, metadata is gathered from multiple sources before the LLM call:

| Source | Data Extracted |
|--------|---------------|
| GitHub API (PyGithub) | repo name, description, homepage (demo URL), topics (tags), primary language |
| README.md | project description, feature details, usage context |
| package.json | JS/TS dependencies (mapped to tech stack names) |
| requirements.txt / pyproject.toml | Python dependencies |
| Cargo.toml / go.mod / Gemfile / etc. | Other ecosystem dependencies |

Only dependency *names* are extracted (not full file content). The LLM maps raw package names to clean display names (e.g. `tailwindcss` to `Tailwind CSS`).

### Functions

**`ingest_from_repo(llm, repo_url_or_path, extra_description=None) -> ProjectConfig`**
- If GitHub URL: fetch metadata via PyGithub, then shallow-clone to read files
- If local path: read files directly, skip GitHub API
- Build context from all sources, call LLM with `with_structured_output(ProjectConfig)`
- Clean up temp clone dir

**`ingest_from_description(llm, text) -> ProjectConfig`**
- If text contains a GitHub URL, extract it and include as context
- Call LLM with `with_structured_output(ProjectConfig)`

**`ingest_interactive(llm) -> ProjectConfig`**
- Prompt user: "Tell me about your project (paste a URL, describe it, or both)"
- If input contains a GitHub URL, route to `ingest_from_repo` with remaining text as extra context
- Otherwise, route to `ingest_from_description`
- Ask follow-up questions if `repo_url` or `demo_url` are missing

**`confirm_config(config) -> ProjectConfig | None`**
- Display extracted config in a Rich table
- Prompt: `Proceed? [y/n/edit]`
- If `edit`: field-by-field editing via Rich prompts (show current value, Enter to keep)
- Returns confirmed config or None if cancelled

**`save_config_json(config, path)`**
- Serialize ProjectConfig to JSON file (for `--save-config` flag)

**`fetch_github_metadata(repo_url) -> dict`**
- Uses PyGithub (already a dependency) to fetch repo metadata
- Works without `GITHUB_TOKEN` for public repos (60 req/hr unauthenticated limit)
- Graceful fallback to empty dict on any failure

### LLM Prompt

The `INGEST_SYSTEM_PROMPT` instructs the LLM to:
- Extract a concise, naturally capitalized title
- Write a polished 1-2 sentence description
- Map dependency names to clean display names for tech_stack
- Infer 3-6 domain/purpose tags
- Extract repo_url and demo_url from context

Uses the same `with_structured_output(ProjectConfig)` pattern as the existing analysis and generation steps.

---

## 3. Confirmation Flow

After extraction, the user sees the results and can accept, reject, or edit:

```
Extracted Project Config
  Title        PinPlace
  Description  A collaborative mapping web app where users create shareable
               maps and others add location pins in real-time
  Repo URL     https://github.com/aringadre76/pinplace
  Demo URL     https://pinplace.vercel.app/
  Tech Stack   React, TypeScript, Vite, Tailwind CSS, Leaflet, Firebase
  Tags         collaborative, maps, real-time, firebase, geolocation

Proceed? [y/n/edit]:
```

If the user chooses `edit`, each field is prompted individually with the current value as the default (press Enter to keep).

---

## 4. Pipeline Flow (Updated)

For `autofolio add`:

```
1. Ingest: gather project metadata from repo/description/interactive input
2. LLM extraction: produce ProjectConfig via structured output
3. Confirmation: display config, get user approval (with optional editing)
4. (Optional) Save config to JSON if --save-config is set
5. [Existing pipeline from here]
6. Detect portfolio stack
7. LLM Analysis (portfolio priority, resume-worthiness)
8. LLM Generation (portfolio patches)
9. Profile README step
10. Dry-run checkpoint or apply
11. Build verification, commit, push, PR
12. Resume snippet generation
```

For `autofolio run`, the flow is unchanged (starts at step 6 with a pre-existing config file).

---

## 5. Dependency Files Scanned

| File | Ecosystem | What is Extracted |
|------|-----------|-------------------|
| `package.json` | JS/TS | dependency and devDependency names |
| `requirements.txt` | Python | package names (before version specifiers) |
| `pyproject.toml` | Python | quoted strings from dependencies section |
| `Cargo.toml` | Rust | full content (truncated) |
| `go.mod` | Go | full content (truncated) |
| `pom.xml` / `build.gradle` | Java/Kotlin | full content (truncated) |
| `Gemfile` | Ruby | full content (truncated) |

---

## 6. Key Decisions

| Decision | Answer |
|----------|--------|
| CLI structure | click.group() with `run` (existing) and `add` (ingest) subcommands |
| Input modes | Repo URL, `--describe` text, `--interactive` prompt (all three supported) |
| GitHub metadata | PyGithub (already a dependency), works unauthenticated for public repos |
| LLM extraction | Same `with_structured_output(ProjectConfig)` pattern as existing pipeline |
| Confirmation | Rich table display with y/n/edit prompt |
| Config persistence | Optional `--save-config` flag for power users and scripting |
| Backward compatibility | `autofolio run --config` preserves exact existing behavior |

---

## Phase 4: Chat UI

A ChatGPT-style web interface using [Chainlit](https://chainlit.io) so users can add projects through conversation instead of (or in addition to) the CLI.

### Architecture

- **Entry point**: `autofolio/web/app.py`. Run with `chainlit run autofolio/web/app.py -w`.
- **Lifecycle**: `@cl.on_chat_start` initializes the LLM and sends ChatSettings (portfolio path/URL, provider, apply mode, skip build). `@cl.on_message` routes input to repo ingest (if GitHub URL detected) or description ingest, then shows extracted config with Approve / Edit / Cancel actions.
- **Actions**: `approve_config` runs the portfolio pipeline (detect stack, analysis, generation), shows diff preview, then Apply or Discard. `edit_config` uses AskActionMessage and AskUserMessage for field-by-field edits. `apply_patches` creates branch, applies patches, runs build (if enabled), commits, pushes, and creates PR.
- **Existing code**: All ingest and pipeline logic is reused from `ingest.py`, `llm.py`, `detector.py`, `patcher.py`, `preview.py`, `git_ops.py`. Sync functions are wrapped with `cl.make_async()` so the Chainlit event loop is not blocked.

### File structure

- `autofolio/web/app.py` – Chainlit app (on_chat_start, set_starters, set_chat_profiles, on_message, action callbacks).
- `.chainlit/config.toml` – Chainlit 2.x config (project root, UI name, description, default_theme, cot, custom_css).
- `public/theme.json` – Teal/cyan HSL theme (light and dark) aligned with CLI branding.
- `public/stylesheet.css` – Extra CSS (config cards, steps, code blocks, buttons).
- `public/avatars/autofolio.png` – Bot avatar.

### UX and theming

- **Theme**: Primary `187 80% 42%` (teal), dark default, Inter font. Both light and dark variants in `public/theme.json`.
- **Settings**: Portfolio path, portfolio URL, LLM provider (ollama/openai), Apply changes (toggle), Skip build (toggle). Stored in session and applied when running the pipeline.
- **Starters**: Four suggestion cards (Add from GitHub, Describe a project, Add multiple, Run from config hint).
- **Steps**: Tool-call steps for "Fetching GitHub metadata", "Cloning and extracting", "Detecting portfolio stack", "Analyzing and generating patches", "Creating branch", "Applying patches", "Build verification", "Committing and pushing".

### Key decisions

| Decision | Answer |
|----------|--------|
| Dependency | Chainlit as optional `web` extra; core CLI installable without it |
| Sync code | `cl.make_async()` for all sync ingest/pipeline calls; no changes to existing modules |
| Config | Portfolio path, provider, apply mode in ChatSettings sidebar; no auth in v1 |
| Pipeline scope | Single-project flow in chat; profile README and resume snippets deferred from web UI v1 |
| COT display | `cot = "tool_call"` so users see step labels without raw prompts |
