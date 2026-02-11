from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autofolio.config import ProjectConfig
from autofolio.ingest import (
    GITHUB_URL_RE,
    _build_ingest_context,
    _read_dependency_info,
    _read_readme,
    fetch_github_metadata,
    ingest_from_description,
    ingest_from_repo,
    parse_github_url,
    save_config_json,
)


@pytest.fixture
def sample_project() -> ProjectConfig:
    return ProjectConfig(
        title="PinPlace",
        description="A collaborative mapping web app",
        repo_url="https://github.com/user/pinplace",
        demo_url="https://pinplace.vercel.app/",
        tech_stack=["React", "TypeScript", "Firebase"],
        tags=["collaborative", "maps", "real-time"],
    )


class TestParseGithubUrl:
    def test_https_url(self):
        result = parse_github_url("https://github.com/user/repo")
        assert result == ("user", "repo")

    def test_https_url_with_git(self):
        result = parse_github_url("https://github.com/user/repo.git")
        assert result == ("user", "repo")

    def test_http_url(self):
        result = parse_github_url("http://github.com/owner/project")
        assert result == ("owner", "project")

    def test_url_with_extra_path(self):
        result = parse_github_url(
            "https://github.com/aringadre76/pinplace/tree/main"
        )
        assert result == ("aringadre76", "pinplace")

    def test_non_github_url(self):
        result = parse_github_url("https://gitlab.com/user/repo")
        assert result is None

    def test_empty_string(self):
        result = parse_github_url("")
        assert result is None

    def test_plain_text(self):
        result = parse_github_url("not a url at all")
        assert result is None

    def test_owner_with_dots(self):
        result = parse_github_url("https://github.com/my.user/my-repo")
        assert result == ("my.user", "my-repo")

    def test_owner_with_hyphens(self):
        result = parse_github_url("https://github.com/my-user/my-repo")
        assert result == ("my-user", "my-repo")


class TestGithubUrlRegex:
    def test_matches_github_url_in_text(self):
        text = "Check out https://github.com/user/repo for more"
        m = GITHUB_URL_RE.search(text)
        assert m is not None
        assert m.group(1) == "user"
        assert m.group(2) == "repo"

    def test_no_match_for_non_github(self):
        text = "Visit https://example.com/user/repo"
        m = GITHUB_URL_RE.search(text)
        assert m is None


class TestReadReadme:
    def test_reads_readme_md(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# My Project\n\nHello world")
        result = _read_readme(tmp_path)
        assert result is not None
        assert "My Project" in result

    def test_reads_lowercase_readme(self, tmp_path: Path):
        (tmp_path / "readme.md").write_text("# Lower case")
        result = _read_readme(tmp_path)
        assert result is not None
        assert "Lower case" in result

    def test_no_readme(self, tmp_path: Path):
        result = _read_readme(tmp_path)
        assert result is None

    def test_truncates_long_readme(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("x" * 5000)
        result = _read_readme(tmp_path)
        assert result is not None
        assert "truncated" in result
        assert len(result) < 5000


class TestReadDependencyInfo:
    def test_reads_package_json(self, tmp_path: Path):
        pkg = {
            "dependencies": {"react": "^18.0", "firebase": "^10.0"},
            "devDependencies": {"typescript": "^5.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        result = _read_dependency_info(tmp_path)
        assert "react" in result
        assert "firebase" in result
        assert "typescript" in result

    def test_reads_requirements_txt(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text(
            "flask>=2.0\nrequests\nnumpy==1.24\n"
        )
        result = _read_dependency_info(tmp_path)
        assert "flask" in result
        assert "requests" in result
        assert "numpy" in result

    def test_reads_pyproject_toml(self, tmp_path: Path):
        content = '[project]\ndependencies = ["click", "rich", "pydantic"]\n'
        (tmp_path / "pyproject.toml").write_text(content)
        result = _read_dependency_info(tmp_path)
        assert "click" in result
        assert "rich" in result

    def test_no_dep_files(self, tmp_path: Path):
        result = _read_dependency_info(tmp_path)
        assert result == ""

    def test_invalid_package_json(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("not json")
        result = _read_dependency_info(tmp_path)
        assert result == ""


class TestBuildIngestContext:
    def test_with_all_sources(self):
        ctx = _build_ingest_context(
            repo_url="https://github.com/user/repo",
            github_meta={
                "name": "repo",
                "description": "A cool project",
                "homepage": "https://cool.app",
                "topics": ["web", "cool"],
                "language": "TypeScript",
            },
            readme_text="# My Repo\n\nDoes cool things",
            dep_info="package.json dependencies: react, next",
            user_description="This is my favorite project",
        )
        assert "https://github.com/user/repo" in ctx
        assert "A cool project" in ctx
        assert "https://cool.app" in ctx
        assert "web, cool" in ctx
        assert "TypeScript" in ctx
        assert "My Repo" in ctx
        assert "react, next" in ctx
        assert "favorite project" in ctx

    def test_with_only_description(self):
        ctx = _build_ingest_context(user_description="A mapping app")
        assert "A mapping app" in ctx
        assert "GitHub API" not in ctx

    def test_with_only_repo_url(self):
        ctx = _build_ingest_context(
            repo_url="https://github.com/user/repo"
        )
        assert "https://github.com/user/repo" in ctx

    def test_empty_github_meta(self):
        ctx = _build_ingest_context(github_meta={})
        assert "GitHub API" not in ctx


class TestFetchGithubMetadata:
    def test_non_github_url_returns_empty(self):
        result = fetch_github_metadata("https://gitlab.com/user/repo")
        assert result == {}

    @patch("github.Github")
    def test_successful_fetch(self, mock_github_cls):
        mock_repo = MagicMock()
        mock_repo.name = "pinplace"
        mock_repo.description = "A mapping app"
        mock_repo.homepage = "https://pinplace.vercel.app"
        mock_repo.language = "TypeScript"
        mock_repo.get_topics.return_value = ["maps", "real-time"]

        mock_g = MagicMock()
        mock_g.get_repo.return_value = mock_repo
        mock_github_cls.return_value = mock_g

        result = fetch_github_metadata("https://github.com/user/pinplace")
        assert result["name"] == "pinplace"
        assert result["description"] == "A mapping app"
        assert result["homepage"] == "https://pinplace.vercel.app"
        assert result["topics"] == ["maps", "real-time"]
        assert result["language"] == "TypeScript"

    @patch("github.Github")
    def test_api_failure_returns_empty(self, mock_github_cls):
        mock_github_cls.side_effect = Exception("rate limited")
        result = fetch_github_metadata("https://github.com/user/repo")
        assert result == {}


class TestIngestFromDescription:
    def test_returns_project_config(self):
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = ProjectConfig(
            title="PinPlace",
            description="Collaborative mapping app",
            repo_url="https://github.com/user/pinplace",
            demo_url="",
            tech_stack=["React", "Firebase"],
            tags=["maps"],
        )
        mock_llm.with_structured_output.return_value = mock_structured

        result = ingest_from_description(
            mock_llm,
            "PinPlace is a collaborative mapping app using React and Firebase. "
            "Repo: https://github.com/user/pinplace"
        )

        assert result.title == "PinPlace"
        assert result.description == "Collaborative mapping app"
        assert "React" in result.tech_stack
        mock_llm.with_structured_output.assert_called_once_with(ProjectConfig)

    def test_detects_github_url_in_text(self):
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = ProjectConfig(
            title="Test",
            description="Test project",
            repo_url="https://github.com/user/test",
        )
        mock_llm.with_structured_output.return_value = mock_structured

        result = ingest_from_description(
            mock_llm,
            "My project at https://github.com/user/test does stuff"
        )

        call_args = mock_structured.invoke.call_args
        messages = call_args[0][0]
        user_msg = messages[1].content
        assert "https://github.com/user/test" in user_msg


class TestIngestFromRepo:
    @patch("autofolio.ingest.fetch_github_metadata")
    @patch("autofolio.ingest.cleanup_temp")
    @patch("autofolio.ingest.clone_repo")
    def test_url_mode_fetches_metadata_and_clones(
        self, mock_clone, mock_cleanup, mock_fetch, tmp_path
    ):
        mock_clone.return_value = tmp_path
        mock_fetch.return_value = {
            "name": "pinplace",
            "description": "A mapping app",
            "homepage": "https://pinplace.vercel.app",
            "topics": ["maps"],
            "language": "TypeScript",
        }
        (tmp_path / "README.md").write_text("# PinPlace\n\nMapping app")
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"react": "^18"}})
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = ProjectConfig(
            title="PinPlace",
            description="A mapping app",
            repo_url="https://github.com/user/pinplace",
            demo_url="https://pinplace.vercel.app",
            tech_stack=["React", "TypeScript"],
            tags=["maps"],
        )
        mock_llm.with_structured_output.return_value = mock_structured

        result = ingest_from_repo(
            mock_llm, "https://github.com/user/pinplace"
        )

        assert result.title == "PinPlace"
        assert result.repo_url == "https://github.com/user/pinplace"
        mock_fetch.assert_called_once()
        mock_clone.assert_called_once()
        mock_cleanup.assert_called_once()

    def test_local_mode_reads_directly(self, tmp_path):
        (tmp_path / "README.md").write_text("# LocalProj\n\nA local project")
        (tmp_path / "requirements.txt").write_text("flask\nrequests\n")

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = ProjectConfig(
            title="LocalProj",
            description="A local project",
            repo_url="",
            tech_stack=["Flask"],
            tags=["web"],
        )
        mock_llm.with_structured_output.return_value = mock_structured

        result = ingest_from_repo(mock_llm, str(tmp_path))

        assert result.title == "LocalProj"
        assert result.repo_url == ""
        mock_llm.with_structured_output.assert_called_once_with(ProjectConfig)

    def test_invalid_path_raises(self):
        mock_llm = MagicMock()
        with pytest.raises(ValueError, match="Not a valid"):
            ingest_from_repo(mock_llm, "/nonexistent/path/to/nowhere")


class TestSaveConfigJson:
    def test_saves_valid_json(self, tmp_path, sample_project):
        out = tmp_path / "out.json"
        save_config_json(sample_project, out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert data["title"] == "PinPlace"
        assert data["description"] == "A collaborative mapping web app"
        assert data["repo_url"] == "https://github.com/user/pinplace"
        assert "React" in data["tech_stack"]
        assert "maps" in data["tags"]

    def test_file_ends_with_newline(self, tmp_path, sample_project):
        out = tmp_path / "out.json"
        save_config_json(sample_project, out)
        text = out.read_text()
        assert text.endswith("\n")


class TestConfirmConfig:
    @patch("autofolio.ingest.Prompt.ask", return_value="y")
    def test_confirm_yes(self, _mock_ask, sample_project):
        from autofolio.ingest import confirm_config
        result = confirm_config(sample_project)
        assert result is not None
        assert result.title == "PinPlace"

    @patch("autofolio.ingest.Prompt.ask", return_value="n")
    def test_confirm_no(self, _mock_ask, sample_project):
        from autofolio.ingest import confirm_config
        result = confirm_config(sample_project)
        assert result is None

    @patch("autofolio.ingest.Prompt.ask")
    def test_confirm_edit(self, mock_ask, sample_project):
        mock_ask.side_effect = [
            "edit",
            "New Title",
            "New description",
            "https://github.com/user/new",
            "",
            "Python, Go",
            "backend, api",
            "y",
        ]
        from autofolio.ingest import confirm_config
        result = confirm_config(sample_project)
        assert result is not None
        assert result.title == "New Title"
        assert result.description == "New description"
        assert result.repo_url == "https://github.com/user/new"
        assert result.tech_stack == ["Python", "Go"]
        assert result.tags == ["backend", "api"]


class TestIngestInteractive:
    @patch("autofolio.ingest.Prompt.ask")
    @patch("autofolio.ingest.ingest_from_repo")
    def test_with_url_input(self, mock_ingest_repo, mock_ask):
        mock_ask.side_effect = [
            "https://github.com/user/myproject this is cool",
            "",
            "",
        ]
        mock_ingest_repo.return_value = ProjectConfig(
            title="MyProject",
            description="A cool project",
            repo_url="https://github.com/user/myproject",
            tech_stack=["Python"],
            tags=["cool"],
        )

        from autofolio.ingest import ingest_interactive
        mock_llm = MagicMock()
        result = ingest_interactive(mock_llm)

        assert result.title == "MyProject"
        mock_ingest_repo.assert_called_once_with(
            mock_llm,
            "https://github.com/user/myproject",
            extra_description="this is cool",
        )

    @patch("autofolio.ingest.Prompt.ask")
    @patch("autofolio.ingest.ingest_from_description")
    def test_with_text_input(self, mock_ingest_desc, mock_ask):
        mock_ask.side_effect = [
            "A weather dashboard using React and D3",
            "https://github.com/user/weather",
            "https://weather.demo.app",
        ]
        mock_ingest_desc.return_value = ProjectConfig(
            title="Weather Dashboard",
            description="Weather visualization app",
            repo_url="",
            demo_url="",
            tech_stack=["React", "D3"],
            tags=["weather"],
        )

        from autofolio.ingest import ingest_interactive
        mock_llm = MagicMock()
        result = ingest_interactive(mock_llm)

        assert result.title == "Weather Dashboard"
        assert result.repo_url == "https://github.com/user/weather"
        assert result.demo_url == "https://weather.demo.app"
        mock_ingest_desc.assert_called_once()
