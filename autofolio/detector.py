from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

StackType = Literal[
    "nextjs",
    "react-vite",
    "hugo",
    "jekyll",
    "astro",
    "gatsby",
    "sveltekit",
    "nuxt",
    "eleventy",
    "angular",
    "vue-vite",
    "remix",
    "static",
    "other",
]

PackageManager = Literal["npm", "yarn", "pnpm", "bun"]

_JS_STACK_BUILD: dict[str, list[str]] = {
    "nextjs": ["{pm} install", "{pm} run build"],
    "react-vite": ["{pm} install", "{pm} run build"],
    "astro": ["{pm} install", "{pm} run build"],
    "gatsby": ["{pm} install", "{pm} run build"],
    "sveltekit": ["{pm} install", "{pm} run build"],
    "nuxt": ["{pm} install", "{pm} run build"],
    "eleventy": ["{pm} install", "{pm} run build"],
    "angular": ["{pm} install", "{pm} run build"],
    "vue-vite": ["{pm} install", "{pm} run build"],
    "remix": ["{pm} install", "{pm} run build"],
}

_NON_JS_BUILD: dict[str, list[str]] = {
    "hugo": ["hugo --minify"],
    "jekyll": ["bundle exec jekyll build"],
    "static": [],
    "other": [],
}


def detect_package_manager(repo_path: Path) -> PackageManager:
    if (repo_path / "bun.lockb").exists() or (repo_path / "bun.lock").exists():
        return "bun"
    if (repo_path / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo_path / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _resolve_pm(cmd: str, pm: PackageManager) -> str:
    if pm == "npm":
        return cmd.replace("{pm}", "npm")
    if pm == "yarn":
        return cmd.replace("{pm} install", "yarn install").replace("{pm} run", "yarn")
    if pm == "pnpm":
        return cmd.replace("{pm}", "pnpm")
    if pm == "bun":
        return cmd.replace("{pm}", "bun")
    return cmd.replace("{pm}", "npm")


def get_build_commands(stack: StackType, pm: PackageManager) -> list[str]:
    if stack in _JS_STACK_BUILD:
        return [_resolve_pm(c, pm) for c in _JS_STACK_BUILD[stack]]
    return list(_NON_JS_BUILD.get(stack, []))


@dataclass
class ProjectListingHint:
    file_path: str
    variable_name: str
    sample_entry: str
    last_entry_marker: str
    entry_count: int


@dataclass
class DetectionResult:
    stack: StackType
    build_commands: list[str]
    file_tree: list[str]
    package_manager: PackageManager = "npm"
    key_files: dict[str, str] = field(default_factory=dict)
    project_listing: ProjectListingHint | None = None


def _collect_file_tree(repo_path: Path) -> list[str]:
    paths: list[str] = []
    skip_dirs = {
        ".git", "node_modules", "__pycache__", ".next", "dist",
        "build", ".hugo_build.lock", "_site", ".astro", "venv",
        ".venv", "env", ".svelte-kit", ".nuxt", ".output",
        ".cache", ".parcel-cache", "out", ".angular",
        ".vercel", ".netlify", "vendor",
    }
    for item in sorted(repo_path.rglob("*")):
        if any(part in skip_dirs for part in item.parts):
            continue
        if item.is_file():
            try:
                rel = item.relative_to(repo_path)
            except ValueError:
                continue
            paths.append(str(rel))
    return paths


def _read_json_safe(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def detect_stack(repo_path: str | Path) -> DetectionResult:
    repo_path = Path(repo_path).resolve()
    if not repo_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {repo_path}")

    file_tree = _collect_file_tree(repo_path)
    file_names = {Path(p).name for p in file_tree}
    file_tree_set = set(file_tree)

    if "next.config.js" in file_names or "next.config.mjs" in file_names or "next.config.ts" in file_names:
        stack: StackType = "nextjs"
    elif "astro.config.mjs" in file_names or "astro.config.ts" in file_names:
        stack = "astro"
    elif "gatsby-config.js" in file_names or "gatsby-config.ts" in file_names:
        stack = "gatsby"
    elif "svelte.config.js" in file_names or "svelte.config.ts" in file_names:
        stack = "sveltekit"
    elif "nuxt.config.js" in file_names or "nuxt.config.ts" in file_names:
        stack = "nuxt"
    elif "remix.config.js" in file_names or "remix.config.ts" in file_names:
        stack = "remix"
    elif "angular.json" in file_names:
        stack = "angular"
    elif (
        ".eleventy.js" in file_names
        or "eleventy.config.js" in file_names
        or "eleventy.config.cjs" in file_names
        or ".eleventy.cjs" in file_names
    ):
        stack = "eleventy"
    elif "config.toml" in file_names and "hugo" in _guess_hugo(repo_path):
        stack = "hugo"
    elif "_config.yml" in file_names or "_config.yaml" in file_names:
        stack = "jekyll"
    elif "vite.config.js" in file_names or "vite.config.ts" in file_names:
        stack = _check_vite_framework(repo_path)
    elif "package.json" in file_names:
        stack = _check_package_json(repo_path)
    elif any(f == "index.html" or f.endswith("/index.html") for f in file_tree_set):
        stack = "static"
    else:
        stack = "other"

    pm = detect_package_manager(repo_path)
    build_commands = get_build_commands(stack, pm)

    key_files = _find_key_files(repo_path, file_tree)
    project_listing = detect_project_listing(repo_path, file_tree)

    return DetectionResult(
        stack=stack,
        build_commands=build_commands,
        file_tree=file_tree,
        package_manager=pm,
        key_files=key_files,
        project_listing=project_listing,
    )


def _guess_hugo(repo_path: Path) -> str:
    config = repo_path / "config.toml"
    if config.exists():
        try:
            text = config.read_text(encoding="utf-8").lower()
            if "hugo" in text or "baseurl" in text:
                return "hugo"
        except OSError:
            pass
    if (repo_path / "themes").is_dir() or (repo_path / "layouts").is_dir():
        return "hugo"
    return ""


def _check_vite_framework(repo_path: Path) -> StackType:
    data = _read_json_safe(repo_path / "package.json")
    if data is None:
        return "react-vite"
    deps = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))
    if "vue" in deps or "@vitejs/plugin-vue" in deps:
        return "vue-vite"
    if "svelte" in deps or "@sveltejs/vite-plugin-svelte" in deps:
        return "sveltekit"
    return "react-vite"


def _check_package_json(repo_path: Path) -> StackType:
    data = _read_json_safe(repo_path / "package.json")
    if data is None:
        return "other"

    deps = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))

    if "next" in deps:
        return "nextjs"
    if "astro" in deps:
        return "astro"
    if "gatsby" in deps:
        return "gatsby"
    if "@sveltejs/kit" in deps:
        return "sveltekit"
    if "nuxt" in deps or "nuxt3" in deps:
        return "nuxt"
    if "@remix-run/react" in deps:
        return "remix"
    if "@angular/core" in deps:
        return "angular"
    if "@11ty/eleventy" in deps:
        return "eleventy"
    if "vite" in deps and "vue" in deps:
        return "vue-vite"
    if "vite" in deps:
        return "react-vite"
    if "react" in deps:
        return "react-vite"

    return "other"


CODE_EXTENSIONS = {
    ".tsx", ".jsx", ".ts", ".js", ".astro", ".svelte", ".vue",
    ".php", ".erb", ".ejs", ".hbs", ".njk", ".pug", ".liquid",
}
DATA_EXTENSIONS = {".json", ".yaml", ".yml", ".toml"}
CONTENT_EXTENSIONS = {".md", ".mdx"}
HTML_EXTENSIONS = {".html", ".htm"}

ARRAY_PATTERN = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*(?::\s*[^=]+)?\s*=\s*\[",
    re.MULTILINE,
)

HTML_REPEATED_BLOCK_PATTERN = re.compile(
    r"<(div|article|section|li|a|card)\s+[^>]*"
    r"(?:class|className)\s*=\s*[\"'][^\"']*"
    r"(project|portfolio|work|card|item)[^\"']*[\"']",
    re.IGNORECASE,
)

KEY_FILE_PATTERNS = [
    "package.json",
    "index.html",
    "projects.html",
    "portfolio.html",
    "work.html",
    "src/App.tsx",
    "src/App.jsx",
    "src/App.vue",
    "src/App.svelte",
    "src/app.tsx",
    "src/app.jsx",
    "src/pages/index.tsx",
    "src/pages/index.jsx",
    "src/pages/index.astro",
    "src/pages/index.svelte",
    "src/pages/index.vue",
    "src/pages/projects.tsx",
    "src/pages/projects.jsx",
    "src/pages/projects.astro",
    "src/pages/projects.svelte",
    "src/pages/projects.vue",
    "src/app/page.tsx",
    "src/app/page.jsx",
    "src/app/projects/page.tsx",
    "src/routes/+page.svelte",
    "src/routes/projects/+page.svelte",
    "pages/index.tsx",
    "pages/index.jsx",
    "pages/index.vue",
    "pages/projects.tsx",
    "pages/projects.vue",
    "app/page.tsx",
    "app/projects/page.tsx",
    "app/routes/_index.tsx",
    "app/routes/projects.tsx",
    "src/app/app.component.html",
    "src/app/projects/projects.component.html",
    "content/projects.md",
    "data/projects.json",
    "data/projects.yaml",
    "data/projects.yml",
    "_data/projects.yml",
    "_data/projects.json",
    "_data/projects.yaml",
    "_includes/projects.html",
    "_includes/projects.njk",
    "_includes/projects.liquid",
    "src/data/projects.json",
    "src/data/projects.ts",
    "src/data/projects.js",
]


def _read_text_safe(path: Path, max_bytes: int = 200_000) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _find_key_files(repo_path: Path, file_tree: list[str]) -> dict[str, str]:
    tree_set = set(file_tree)
    found: dict[str, str] = {}
    for pattern in KEY_FILE_PATTERNS:
        if pattern in tree_set:
            content = _read_text_safe(repo_path / pattern)
            if content is not None:
                found[pattern] = content

    for fpath in file_tree:
        if fpath in found:
            continue
        ext = Path(fpath).suffix.lower()
        if ext not in HTML_EXTENSIONS:
            continue
        content = _read_text_safe(repo_path / fpath)
        if content is None:
            continue
        content_lower = content.lower()
        if any(
            kw in content_lower
            for kw in ("project", "portfolio", "work", "card")
        ):
            found[fpath] = content

    return found


def _extract_array_block(text: str, match_start: int) -> str | None:
    bracket_start = text.index("[", match_start)
    depth = 0
    i = bracket_start
    while i < len(text):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[bracket_start : i + 1]
        i += 1
    return None


def _find_last_object_in_array(array_text: str) -> tuple[str, str] | None:
    brace_positions = []
    depth = 0
    i = 0
    current_start = -1
    while i < len(array_text):
        ch = array_text[i]
        if ch == "{":
            if depth == 0:
                current_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and current_start >= 0:
                brace_positions.append((current_start, i + 1))
        i += 1

    if not brace_positions:
        return None

    last_start, last_end = brace_positions[-1]

    line_start = array_text.rfind("\n", 0, last_start)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1

    last_entry = array_text[line_start:last_end]

    end_region = array_text[last_end:]
    marker_suffix = ""
    for ch in end_region:
        if ch in (",", " ", "\t"):
            marker_suffix += ch
        elif ch == "\n":
            break
        else:
            break

    closing_line = "}" + marker_suffix.rstrip()
    if not closing_line or closing_line == "}":
        closing_line = "},"

    return last_entry, closing_line


def _detect_project_listing_code(
    repo_path: Path, file_tree: list[str]
) -> ProjectListingHint | None:
    candidates: list[tuple[str, str, int]] = []

    for fpath in file_tree:
        ext = Path(fpath).suffix
        if ext not in CODE_EXTENSIONS:
            continue

        content = _read_text_safe(repo_path / fpath)
        if content is None:
            continue

        for match in ARRAY_PATTERN.finditer(content):
            var_name = match.group(1).lower()
            if not any(
                kw in var_name
                for kw in ("project", "work", "portfolio", "card", "item")
            ):
                continue

            array_block = _extract_array_block(content, match.start())
            if array_block is None:
                continue

            title_count = len(re.findall(r'title\s*[:=]', array_block))
            desc_count = len(re.findall(r'description\s*[:=]', array_block))

            if title_count >= 2 and desc_count >= 2:
                candidates.append((fpath, match.group(1), title_count))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[2], reverse=True)
    best_file, best_var, entry_count = candidates[0]

    content = _read_text_safe(repo_path / best_file)
    if content is None:
        return None

    for match in ARRAY_PATTERN.finditer(content):
        if match.group(1) == best_var:
            array_block = _extract_array_block(content, match.start())
            if array_block is None:
                continue
            result = _find_last_object_in_array(array_block)
            if result is None:
                continue
            last_entry, marker_line = result
            return ProjectListingHint(
                file_path=best_file,
                variable_name=best_var,
                sample_entry=last_entry,
                last_entry_marker=marker_line,
                entry_count=entry_count,
            )

    return None


def _detect_project_listing_html(
    repo_path: Path, file_tree: list[str]
) -> ProjectListingHint | None:
    candidates: list[tuple[str, str, str, int]] = []

    for fpath in file_tree:
        ext = Path(fpath).suffix.lower()
        if ext not in HTML_EXTENSIONS:
            continue

        content = _read_text_safe(repo_path / fpath)
        if content is None:
            continue

        matches = list(HTML_REPEATED_BLOCK_PATTERN.finditer(content))
        if not matches:
            continue

        tag_classes: dict[str, list[re.Match]] = {}
        for m in matches:
            tag = m.group(1).lower()
            class_attr_start = m.start()
            class_match = re.search(
                r'(?:class|className)\s*=\s*["\']([^"\']+)["\']',
                content[class_attr_start:class_attr_start + 300],
                re.IGNORECASE,
            )
            if class_match:
                key = f"{tag}.{class_match.group(1)}"
                tag_classes.setdefault(key, []).append(m)

        for key, group_matches in tag_classes.items():
            if len(group_matches) < 2:
                continue
            last_match = group_matches[-1]
            tag = last_match.group(1).lower()
            block = _extract_html_block(content, last_match.start(), tag)
            if block:
                candidates.append((fpath, key, block, len(group_matches)))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[3], reverse=True)
    best_file, best_key, sample_block, count = candidates[0]

    last_line = sample_block.strip().splitlines()[-1].strip() if sample_block.strip() else ""

    return ProjectListingHint(
        file_path=best_file,
        variable_name=f"(html:{best_key})",
        sample_entry=sample_block,
        last_entry_marker=last_line,
        entry_count=count,
    )


def _extract_html_block(content: str, start: int, tag: str) -> str | None:
    open_idx = content.rfind("<", 0, start + 1)
    if open_idx < 0:
        open_idx = start

    depth = 0
    i = open_idx
    open_tag = f"<{tag}"
    close_tag = f"</{tag}>"
    open_tag_len = len(open_tag)
    close_tag_len = len(close_tag)
    content_lower = content.lower()

    while i < len(content):
        if content_lower[i:i + open_tag_len] == open_tag:
            next_char_idx = i + open_tag_len
            if next_char_idx < len(content) and content[next_char_idx] in (" ", ">", "\t", "\n", "/"):
                depth += 1
                i += open_tag_len
                continue
        if content_lower[i:i + close_tag_len] == close_tag:
            depth -= 1
            if depth == 0:
                return content[open_idx:i + close_tag_len]
            i += close_tag_len
            continue
        i += 1

    return None


def _detect_project_listing_content(
    repo_path: Path, file_tree: list[str]
) -> ProjectListingHint | None:
    project_dirs = [
        "content/projects", "src/content/projects", "_posts",
        "src/pages/projects", "content/work", "data",
        "src/content", "_projects", "projects",
    ]
    for pdir in project_dirs:
        matching = [f for f in file_tree if f.startswith(pdir + "/")]
        if len(matching) >= 2:
            return ProjectListingHint(
                file_path=pdir,
                variable_name="(directory)",
                sample_entry="",
                last_entry_marker="",
                entry_count=len(matching),
            )
    return None


def detect_project_listing(
    repo_path: Path, file_tree: list[str]
) -> ProjectListingHint | None:
    result = _detect_project_listing_code(repo_path, file_tree)
    if result is not None:
        return result
    result = _detect_project_listing_html(repo_path, file_tree)
    if result is not None:
        return result
    return _detect_project_listing_content(repo_path, file_tree)
