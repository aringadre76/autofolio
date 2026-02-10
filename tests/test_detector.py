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


class TestNotADirectory:
    def test_raises_for_file(self, tmp_repo: Path) -> None:
        f = tmp_repo / "file.txt"
        f.write_text("hi")
        with pytest.raises(NotADirectoryError):
            detect_stack(f)
