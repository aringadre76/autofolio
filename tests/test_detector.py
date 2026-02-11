from __future__ import annotations

import json
from pathlib import Path

import pytest

from autofolio.detector import detect_project_listing, detect_stack


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


def _write(base: Path, rel: str, content: str = "") -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestDetectNextjs:
    def test_next_config_js(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "next.config.js", "module.exports = {}")
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"next": "14.0"}}))
        result = detect_stack(tmp_repo)
        assert result.stack == "nextjs"

    def test_next_config_mjs(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "next.config.mjs", "export default {}")
        result = detect_stack(tmp_repo)
        assert result.stack == "nextjs"

    def test_next_in_package_json_only(self, tmp_repo: Path) -> None:
        _write(
            tmp_repo,
            "package.json",
            json.dumps({"dependencies": {"next": "14.0", "react": "18.0"}}),
        )
        result = detect_stack(tmp_repo)
        assert result.stack == "nextjs"


class TestDetectReactVite:
    def test_vite_config(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "vite.config.ts", "export default {}")
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"react": "18.0"}}))
        result = detect_stack(tmp_repo)
        assert result.stack == "react-vite"

    def test_react_in_package_json(self, tmp_repo: Path) -> None:
        _write(
            tmp_repo,
            "package.json",
            json.dumps({"dependencies": {"react": "18.0"}}),
        )
        result = detect_stack(tmp_repo)
        assert result.stack == "react-vite"


class TestDetectHugo:
    def test_hugo_config(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "config.toml", 'baseURL = "https://example.com"\ntitle = "My Site"')
        result = detect_stack(tmp_repo)
        assert result.stack == "hugo"

    def test_hugo_layouts_dir(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "config.toml", "something = true")
        (tmp_repo / "layouts").mkdir()
        result = detect_stack(tmp_repo)
        assert result.stack == "hugo"


class TestDetectJekyll:
    def test_config_yml(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "_config.yml", "title: My Site")
        result = detect_stack(tmp_repo)
        assert result.stack == "jekyll"


class TestDetectAstro:
    def test_astro_config(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "astro.config.mjs", "export default {}")
        result = detect_stack(tmp_repo)
        assert result.stack == "astro"


class TestDetectStatic:
    def test_plain_html(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "index.html", "<html></html>")
        result = detect_stack(tmp_repo)
        assert result.stack == "static"
        assert result.build_commands == []


class TestDetectOther:
    def test_empty_repo(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "hello.txt", "hi")
        result = detect_stack(tmp_repo)
        assert result.stack == "other"


class TestFileTree:
    def test_skips_git_dir(self, tmp_repo: Path) -> None:
        _write(tmp_repo, ".git/config", "")
        _write(tmp_repo, "index.html", "<html></html>")
        result = detect_stack(tmp_repo)
        assert not any(".git" in p for p in result.file_tree)

    def test_skips_node_modules(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "node_modules/pkg/index.js", "")
        _write(tmp_repo, "index.html", "")
        result = detect_stack(tmp_repo)
        assert not any("node_modules" in p for p in result.file_tree)

    def test_collects_files(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "src/App.tsx", "")
        _write(tmp_repo, "package.json", "{}")
        result = detect_stack(tmp_repo)
        assert "package.json" in result.file_tree
        rel = "src/App.tsx"
        assert rel in result.file_tree


class TestKeyFiles:
    def test_reads_package_json(self, tmp_repo: Path) -> None:
        pkg = json.dumps({"name": "test", "dependencies": {"react": "18"}})
        _write(tmp_repo, "package.json", pkg)
        _write(tmp_repo, "vite.config.ts", "export default {}")
        result = detect_stack(tmp_repo)
        assert "package.json" in result.key_files
        assert "react" in result.key_files["package.json"]

    def test_reads_app_tsx(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"react": "18"}}))
        _write(tmp_repo, "vite.config.ts", "")
        _write(tmp_repo, "src/App.tsx", "export default function App() {}")
        result = detect_stack(tmp_repo)
        assert "src/App.tsx" in result.key_files


class TestProjectListingDetection:
    def test_detects_tsx_array(self, tmp_repo: Path) -> None:
        code = '''
const projectsData = [
  {
    title: "Project A",
    description: "Description A",
    links: [{ label: "GitHub", url: "https://github.com/a" }],
  },
  {
    title: "Project B",
    description: "Description B",
    links: [{ label: "GitHub", url: "https://github.com/b" }],
  },
];
'''
        _write(tmp_repo, "src/App.tsx", code)
        file_tree = ["src/App.tsx"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.file_path == "src/App.tsx"
        assert result.variable_name == "projectsData"
        assert result.entry_count == 2

    def test_detects_exported_array(self, tmp_repo: Path) -> None:
        code = '''
export const projects = [
  { title: "A", description: "desc A" },
  { title: "B", description: "desc B" },
  { title: "C", description: "desc C" },
];
'''
        _write(tmp_repo, "src/data/projects.ts", code)
        file_tree = ["src/data/projects.ts"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name == "projects"
        assert result.entry_count == 3

    def test_ignores_non_project_arrays(self, tmp_repo: Path) -> None:
        code = '''
const navItems = [
  { label: "Home", url: "/" },
  { label: "About", url: "/about" },
];
'''
        _write(tmp_repo, "src/Nav.tsx", code)
        file_tree = ["src/Nav.tsx"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is None

    def test_no_listing_in_empty_repo(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "index.html", "<html></html>")
        result = detect_project_listing(tmp_repo, ["index.html"])
        assert result is None

    def test_sample_entry_populated(self, tmp_repo: Path) -> None:
        code = '''
const projectsData = [
  {
    title: "First",
    description: "First project",
  },
  {
    title: "Second",
    description: "Second project",
  },
];
'''
        _write(tmp_repo, "src/App.tsx", code)
        file_tree = ["src/App.tsx"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert "Second" in result.sample_entry
        assert result.last_entry_marker != ""


class TestProjectListingIntegration:
    def test_detect_stack_populates_listing(self, tmp_repo: Path) -> None:
        code = '''
const projectsData = [
  { title: "A", description: "d1" },
  { title: "B", description: "d2" },
];
'''
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"react": "18"}}))
        _write(tmp_repo, "vite.config.ts", "")
        _write(tmp_repo, "src/App.tsx", code)
        result = detect_stack(tmp_repo)
        assert result.project_listing is not None
        assert result.project_listing.file_path == "src/App.tsx"


class TestExportDefaultArray:
    def test_detects_export_default_array(self, tmp_repo: Path) -> None:
        code = '''
export default [
  {
    title: "Project A",
    description: "Description A",
    url: "https://github.com/a",
  },
  {
    title: "Project B",
    description: "Description B",
    url: "https://github.com/b",
  },
];
'''
        _write(tmp_repo, "src/data/projects.ts", code)
        file_tree = ["src/data/projects.ts"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.file_path == "src/data/projects.ts"
        assert "export-default" in result.variable_name
        assert result.entry_count == 2

    def test_detects_module_exports_array(self, tmp_repo: Path) -> None:
        code = '''
module.exports = [
  {
    title: "Project A",
    description: "Description A",
  },
  {
    title: "Project B",
    description: "Description B",
  },
];
'''
        _write(tmp_repo, "data/projects.js", code)
        file_tree = ["data/projects.js"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.file_path == "data/projects.js"
        assert "module-exports" in result.variable_name
        assert result.entry_count == 2


class TestJsonDataDetection:
    def test_detects_json_project_array(self, tmp_repo: Path) -> None:
        data = json.dumps([
            {"title": "Alpha", "description": "First project", "url": "https://github.com/a"},
            {"title": "Beta", "description": "Second project", "url": "https://github.com/b"},
        ], indent=2)
        _write(tmp_repo, "data/projects.json", data)
        file_tree = ["data/projects.json"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name == "(json-array)"
        assert result.file_path == "data/projects.json"
        assert result.entry_count == 2

    def test_detects_json_nested_array(self, tmp_repo: Path) -> None:
        data = json.dumps({
            "projects": [
                {"title": "A", "description": "Desc A"},
                {"title": "B", "description": "Desc B"},
                {"title": "C", "description": "Desc C"},
            ]
        }, indent=2)
        _write(tmp_repo, "_data/projects.json", data)
        file_tree = ["_data/projects.json"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name == "(json-array)"
        assert result.entry_count == 3

    def test_ignores_non_project_json(self, tmp_repo: Path) -> None:
        data = json.dumps({"name": "my-site", "version": "1.0"})
        _write(tmp_repo, "package.json", data)
        file_tree = ["package.json"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is None

    def test_json_with_name_field(self, tmp_repo: Path) -> None:
        data = json.dumps([
            {"name": "Alpha", "description": "First", "link": "url1"},
            {"name": "Beta", "description": "Second", "link": "url2"},
        ], indent=2)
        _write(tmp_repo, "data/projects.json", data)
        file_tree = ["data/projects.json"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.entry_count == 2


class TestYamlDataDetection:
    def test_detects_yaml_project_list(self, tmp_repo: Path) -> None:
        yaml_content = """- title: Alpha
  description: First project
  url: https://github.com/a
- title: Beta
  description: Second project
  url: https://github.com/b
"""
        _write(tmp_repo, "_data/projects.yml", yaml_content)
        file_tree = ["_data/projects.yml"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name in ("(yaml-list)",)
        assert result.entry_count == 2

    def test_detects_yaml_with_name_field(self, tmp_repo: Path) -> None:
        yaml_content = """- name: Alpha
  description: First project
- name: Beta
  description: Second project
- name: Gamma
  description: Third project
"""
        _write(tmp_repo, "data/projects.yaml", yaml_content)
        file_tree = ["data/projects.yaml"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.entry_count == 3


class TestMarkdownDetection:
    def test_detects_markdown_project_file(self, tmp_repo: Path) -> None:
        md = """# My Projects

## Alpha

A cool ML project for doing things.

[Repo](https://github.com/u/alpha)

## Beta

A web app for tracking stuff.

[Repo](https://github.com/u/beta)

## Gamma

Another great project.

[Repo](https://github.com/u/gamma)
"""
        _write(tmp_repo, "content/projects.md", md)
        file_tree = ["content/projects.md"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name == "(markdown)"
        assert result.file_path == "content/projects.md"

    def test_ignores_non_project_markdown(self, tmp_repo: Path) -> None:
        md = "# About Me\n\nI am a developer.\n"
        _write(tmp_repo, "content/about.md", md)
        file_tree = ["content/about.md"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is None


class TestHtmlDetectionBroadened:
    def test_detects_html_with_project_classes(self, tmp_repo: Path) -> None:
        html = '''<html><body>
<div class="project-card"><a href="url1"><h3>Alpha</h3></a></div>
<div class="project-card"><a href="url2"><h3>Beta</h3></a></div>
<div class="project-card"><a href="url3"><h3>Gamma</h3></a></div>
</body></html>'''
        _write(tmp_repo, "index.html", html)
        file_tree = ["index.html"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name.startswith("(html:")

    def test_detects_html_with_generic_classes_and_links(self, tmp_repo: Path) -> None:
        html = '''<html><body>
<div class="card"><a href="https://github.com/u/a">Alpha</a></div>
<div class="card"><a href="https://github.com/u/b">Beta</a></div>
<div class="card"><a href="https://github.com/u/c">Gamma</a></div>
</body></html>'''
        _write(tmp_repo, "projects.html", html)
        file_tree = ["projects.html"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name.startswith("(html:")

    def test_detects_html_article_elements(self, tmp_repo: Path) -> None:
        html = '''<html><body>
<article class="work-item"><a href="url1">Project 1</a><p>Description 1</p></article>
<article class="work-item"><a href="url2">Project 2</a><p>Description 2</p></article>
</body></html>'''
        _write(tmp_repo, "portfolio.html", html)
        file_tree = ["portfolio.html"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None


class TestContentDirectoryDetection:
    def test_detects_content_directory(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "content/projects/alpha.md", "# Alpha")
        _write(tmp_repo, "content/projects/beta.md", "# Beta")
        file_tree = ["content/projects/alpha.md", "content/projects/beta.md"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name == "(directory)"

    def test_detects_posts_directory(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "_posts/2024-01-01-alpha.md", "# Alpha")
        _write(tmp_repo, "_posts/2024-01-02-beta.md", "# Beta")
        file_tree = ["_posts/2024-01-01-alpha.md", "_posts/2024-01-02-beta.md"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.variable_name == "(directory)"


class TestTypescriptTailwindPortfolio:
    def test_detects_ts_with_tailwind(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "next.config.ts", "export default {}")
        _write(tmp_repo, "tailwind.config.ts", "export default {}")
        _write(tmp_repo, "package.json", json.dumps({
            "dependencies": {"next": "14.0", "react": "18.0"},
            "devDependencies": {"tailwindcss": "3.4"}
        }))
        code = '''
import { StaticImageData } from "next/image";

export interface Project {
  title: string;
  description: string;
  tags: string[];
  link: string;
  image?: StaticImageData;
}

export const projects: Project[] = [
  {
    title: "E-Commerce Platform",
    description: "Full-stack e-commerce with Stripe integration",
    tags: ["Next.js", "TypeScript", "Tailwind CSS", "Stripe"],
    link: "https://github.com/user/ecommerce",
  },
  {
    title: "Chat Application",
    description: "Real-time messaging with WebSocket support",
    tags: ["React", "Node.js", "Socket.io", "Tailwind CSS"],
    link: "https://github.com/user/chat-app",
  },
];
'''
        _write(tmp_repo, "src/data/projects.ts", code)
        result = detect_stack(tmp_repo)
        assert result.stack == "nextjs"
        assert result.project_listing is not None
        assert result.project_listing.file_path == "src/data/projects.ts"
        assert result.project_listing.variable_name == "projects"
        assert result.project_listing.entry_count == 2
        assert "Chat Application" in result.project_listing.sample_entry

    def test_detects_react_vite_tailwind(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "vite.config.ts", "export default {}")
        _write(tmp_repo, "tailwind.config.js", "module.exports = {}")
        _write(tmp_repo, "package.json", json.dumps({
            "dependencies": {"react": "18.0"},
            "devDependencies": {"vite": "5.0", "tailwindcss": "3.4"}
        }))
        code = '''
const projects = [
  {
    title: "Dashboard",
    description: "Analytics dashboard with charts",
    tech: ["React", "Tailwind", "D3"],
    github: "https://github.com/user/dashboard",
  },
  {
    title: "Portfolio",
    description: "Personal portfolio site",
    tech: ["React", "Tailwind"],
    github: "https://github.com/user/portfolio",
  },
];

export default projects;
'''
        _write(tmp_repo, "src/data/projects.ts", code)
        result = detect_stack(tmp_repo)
        assert result.stack == "react-vite"
        assert result.project_listing is not None
        assert result.project_listing.variable_name == "projects"


class TestStaticHtmlPortfolio:
    def test_simple_html_portfolio(self, tmp_repo: Path) -> None:
        html = '''<!DOCTYPE html>
<html>
<head><title>My Portfolio</title></head>
<body>
  <h1>Projects</h1>
  <div class="project-card">
    <h3>Project Alpha</h3>
    <p>A machine learning project</p>
    <a href="https://github.com/user/alpha">View on GitHub</a>
  </div>
  <div class="project-card">
    <h3>Project Beta</h3>
    <p>A web application</p>
    <a href="https://github.com/user/beta">View on GitHub</a>
  </div>
</body>
</html>'''
        _write(tmp_repo, "index.html", html)
        result = detect_stack(tmp_repo)
        assert result.stack == "static"
        assert result.build_commands == []
        assert result.project_listing is not None
        assert result.project_listing.variable_name.startswith("(html:")


class TestDetectionPriority:
    def test_code_detection_beats_html(self, tmp_repo: Path) -> None:
        code = '''
const projects = [
  { title: "A", description: "desc A" },
  { title: "B", description: "desc B" },
];
'''
        html = '''<div class="project-card"><a href="u">A</a></div>
<div class="project-card"><a href="u">B</a></div>'''
        _write(tmp_repo, "src/data.ts", code)
        _write(tmp_repo, "index.html", html)
        file_tree = ["src/data.ts", "index.html"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.file_path == "src/data.ts"

    def test_code_detection_beats_json(self, tmp_repo: Path) -> None:
        code = '''
const projects = [
  { title: "A", description: "desc A" },
  { title: "B", description: "desc B" },
];
'''
        data = json.dumps([
            {"title": "A", "description": "desc A"},
            {"title": "B", "description": "desc B"},
        ])
        _write(tmp_repo, "src/data.ts", code)
        _write(tmp_repo, "data/projects.json", data)
        file_tree = ["src/data.ts", "data/projects.json"]
        result = detect_project_listing(tmp_repo, file_tree)
        assert result is not None
        assert result.file_path == "src/data.ts"


class TestPackageManagerDetection:
    def test_bun_lockfile(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "bun.lockb", "")
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"react": "18"}}))
        _write(tmp_repo, "vite.config.ts", "")
        result = detect_stack(tmp_repo)
        assert result.package_manager == "bun"
        assert any("bun" in cmd for cmd in result.build_commands)

    def test_pnpm_lockfile(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "pnpm-lock.yaml", "")
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"react": "18"}}))
        _write(tmp_repo, "vite.config.ts", "")
        result = detect_stack(tmp_repo)
        assert result.package_manager == "pnpm"
        assert any("pnpm" in cmd for cmd in result.build_commands)

    def test_yarn_lockfile(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "yarn.lock", "")
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"react": "18"}}))
        _write(tmp_repo, "vite.config.ts", "")
        result = detect_stack(tmp_repo)
        assert result.package_manager == "yarn"


class TestMoreFrameworks:
    def test_sveltekit(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "svelte.config.js", "export default {}")
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"@sveltejs/kit": "2.0"}}))
        result = detect_stack(tmp_repo)
        assert result.stack == "sveltekit"

    def test_nuxt(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "nuxt.config.ts", "export default {}")
        result = detect_stack(tmp_repo)
        assert result.stack == "nuxt"

    def test_gatsby(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "gatsby-config.js", "module.exports = {}")
        result = detect_stack(tmp_repo)
        assert result.stack == "gatsby"

    def test_eleventy(self, tmp_repo: Path) -> None:
        _write(tmp_repo, ".eleventy.js", "module.exports = {}")
        result = detect_stack(tmp_repo)
        assert result.stack == "eleventy"

    def test_angular(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "angular.json", "{}")
        result = detect_stack(tmp_repo)
        assert result.stack == "angular"

    def test_remix(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "remix.config.js", "module.exports = {}")
        result = detect_stack(tmp_repo)
        assert result.stack == "remix"

    def test_vue_vite(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "vite.config.ts", "")
        _write(tmp_repo, "package.json", json.dumps({
            "dependencies": {"vue": "3.0", "@vitejs/plugin-vue": "5.0"}
        }))
        result = detect_stack(tmp_repo)
        assert result.stack == "vue-vite"


class TestKeyFileDiscovery:
    def test_discovers_project_named_ts_file(self, tmp_repo: Path) -> None:
        _write(tmp_repo, "package.json", json.dumps({"dependencies": {"react": "18"}}))
        _write(tmp_repo, "vite.config.ts", "")
        _write(tmp_repo, "src/components/Projects.tsx", "export default function Projects() {}")
        result = detect_stack(tmp_repo)
        assert "src/components/Projects.tsx" in result.key_files

    def test_discovers_project_data_json(self, tmp_repo: Path) -> None:
        data = json.dumps([{"title": "A", "description": "d"}])
        _write(tmp_repo, "data/projects.json", data)
        _write(tmp_repo, "index.html", "<html></html>")
        result = detect_stack(tmp_repo)
        assert "data/projects.json" in result.key_files


class TestNotADirectory:
    def test_raises_for_file(self, tmp_repo: Path) -> None:
        f = tmp_repo / "file.txt"
        f.write_text("hi")
        with pytest.raises(NotADirectoryError):
            detect_stack(f)
