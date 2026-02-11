from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from autofolio.cli import main
from autofolio.config import (
    AnalysisResponse,
    Evaluation,
    GenerationResponse,
    PatchAction,
    PlannedAction,
    ProjectConfig,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def portfolio_dir(tmp_path):
    port = tmp_path / "portfolio"
    port.mkdir()
    (port / "package.json").write_text(json.dumps({
        "name": "my-portfolio",
        "dependencies": {"next": "14.0.0", "react": "18.0.0"},
    }))
    data_dir = port / "data"
    data_dir.mkdir()
    projects = [
        {
            "title": "Existing Project One",
            "description": "First project in portfolio",
            "repo_url": "https://github.com/user/project-one",
            "tech": ["React", "Node.js"],
        },
        {
            "title": "Existing Project Two",
            "description": "Second project in portfolio",
            "repo_url": "https://github.com/user/project-two",
            "tech": ["Python", "Flask"],
        },
    ]
    (data_dir / "projects.json").write_text(
        json.dumps(projects, indent=2) + "\n"
    )
    return port


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        "title": "TestProject",
        "description": "A test project for integration tests",
        "repo_url": "https://github.com/user/testproject",
        "demo_url": "https://testproject.demo.app",
        "tech_stack": ["React", "TypeScript"],
        "tags": ["testing", "demo"],
    }
    path = tmp_path / "test_config.json"
    path.write_text(json.dumps(cfg))
    return path


@pytest.fixture
def project_dir(tmp_path):
    proj = tmp_path / "myproject"
    proj.mkdir()
    (proj / "README.md").write_text(
        "# TestProject\n\nA test project built with React and TypeScript.\n"
    )
    (proj / "package.json").write_text(json.dumps({
        "name": "testproject",
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"typescript": "^5.0.0"},
    }))
    return proj


def _make_mock_llm():
    mock_llm = MagicMock()

    canned_analysis = AnalysisResponse(
        evaluation=Evaluation(
            portfolio_priority="top",
            resume_worthy=True,
            reason="Strong project with modern tech stack",
        ),
        files_to_read=["data/projects.json"],
        plan=[
            PlannedAction(
                path="data/projects.json",
                action="replace",
                explain="Replace JSON file with new entry added",
            )
        ],
    )

    new_projects = [
        {
            "title": "Existing Project One",
            "description": "First project in portfolio",
            "repo_url": "https://github.com/user/project-one",
            "tech": ["React", "Node.js"],
        },
        {
            "title": "Existing Project Two",
            "description": "Second project in portfolio",
            "repo_url": "https://github.com/user/project-two",
            "tech": ["Python", "Flask"],
        },
        {
            "title": "TestProject",
            "description": "A test project for integration tests",
            "repo_url": "https://github.com/user/testproject",
            "tech": ["React", "TypeScript"],
        },
    ]

    canned_generation = GenerationResponse(
        patch=[
            PatchAction(
                path="data/projects.json",
                action="replace",
                content=json.dumps(new_projects, indent=2) + "\n",
            )
        ],
        resume_snippet="Developed TestProject using React and TypeScript.",
    )

    canned_project_config = ProjectConfig(
        title="TestProject",
        description="A test project from local ingest",
        repo_url="",
        demo_url="",
        tech_stack=["React"],
        tags=["testing"],
    )

    def _with_structured(schema):
        m = MagicMock()
        if schema is AnalysisResponse:
            m.invoke.return_value = canned_analysis
        elif schema is GenerationResponse:
            m.invoke.return_value = canned_generation
        elif schema is ProjectConfig:
            m.invoke.return_value = canned_project_config
        else:
            m.invoke.return_value = MagicMock()
        return m

    mock_llm.with_structured_output.side_effect = _with_structured

    mock_response = MagicMock()
    mock_response.content = "Developed TestProject, a modern web application."
    mock_llm.invoke.return_value = mock_response

    return mock_llm


class TestRunDryRunFlow:

    def test_full_dry_run_pipeline(self, runner, portfolio_dir, config_file):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            result = runner.invoke(main, [
                "run",
                "--config", str(config_file),
                "--portfolio-path", str(portfolio_dir),
                "--no-profile",
            ])
        assert result.exit_code == 0, (
            f"Expected exit code 0 but got {result.exit_code}.\n"
            f"Exception: {result.exception}"
        )
        call_schemas = [
            call.args[0]
            for call in mock_llm.with_structured_output.call_args_list
        ]
        assert AnalysisResponse in call_schemas
        assert GenerationResponse in call_schemas

    def test_dry_run_does_not_modify_portfolio(
        self, runner, portfolio_dir, config_file
    ):
        original = (portfolio_dir / "data" / "projects.json").read_text()
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            result = runner.invoke(main, [
                "run",
                "--config", str(config_file),
                "--portfolio-path", str(portfolio_dir),
                "--no-profile",
            ])
        assert result.exit_code == 0
        after = (portfolio_dir / "data" / "projects.json").read_text()
        assert original == after

    def test_dry_run_calls_analysis_before_generation(
        self, runner, portfolio_dir, config_file
    ):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            result = runner.invoke(main, [
                "run",
                "--config", str(config_file),
                "--portfolio-path", str(portfolio_dir),
                "--no-profile",
            ])
        assert result.exit_code == 0
        schemas_in_order = [
            call.args[0]
            for call in mock_llm.with_structured_output.call_args_list
        ]
        analysis_idx = schemas_in_order.index(AnalysisResponse)
        generation_idx = schemas_in_order.index(GenerationResponse)
        assert analysis_idx < generation_idx

    def test_dry_run_with_resume_snippet(
        self, runner, portfolio_dir, config_file
    ):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            result = runner.invoke(main, [
                "run",
                "--config", str(config_file),
                "--portfolio-path", str(portfolio_dir),
                "--no-profile",
            ])
        assert result.exit_code == 0
        mock_llm.invoke.assert_not_called()

    def test_dry_run_generates_resume_when_snippet_missing(
        self, runner, portfolio_dir, config_file
    ):
        mock_llm = _make_mock_llm()
        original_side_effect = mock_llm.with_structured_output.side_effect

        def _with_structured_no_snippet(schema):
            m = original_side_effect(schema)
            if schema is GenerationResponse:
                gen = m.invoke.return_value
                gen.resume_snippet = None
            return m

        mock_llm.with_structured_output.side_effect = _with_structured_no_snippet

        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            result = runner.invoke(main, [
                "run",
                "--config", str(config_file),
                "--portfolio-path", str(portfolio_dir),
                "--no-profile",
            ])
        assert result.exit_code == 0
        mock_llm.invoke.assert_called()

    def test_dry_run_loads_config_correctly(
        self, runner, portfolio_dir, config_file
    ):
        mock_llm = _make_mock_llm()

        invoked_projects = []
        original_side_effect = mock_llm.with_structured_output.side_effect

        def _capture_project(schema):
            m = original_side_effect(schema)
            if schema is AnalysisResponse:
                original_invoke = m.invoke

                def capturing_invoke(messages):
                    user_msg = messages[1].content
                    if "TestProject" in user_msg:
                        invoked_projects.append("TestProject")
                    return original_invoke(messages)

                m.invoke = capturing_invoke
            return m

        mock_llm.with_structured_output.side_effect = _capture_project

        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            result = runner.invoke(main, [
                "run",
                "--config", str(config_file),
                "--portfolio-path", str(portfolio_dir),
                "--no-profile",
            ])
        assert result.exit_code == 0
        assert "TestProject" in invoked_projects


class TestAddDryRunFlow:

    def test_add_local_project_dry_run(
        self, runner, portfolio_dir, project_dir
    ):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            with patch(
                "autofolio.ingest.confirm_config",
                side_effect=lambda c: c,
            ):
                result = runner.invoke(main, [
                    "add",
                    str(project_dir),
                    "--portfolio-path", str(portfolio_dir),
                    "--no-profile",
                ])
        assert result.exit_code == 0, (
            f"Expected exit code 0 but got {result.exit_code}.\n"
            f"Exception: {result.exception}"
        )
        project_config_calls = [
            call for call in mock_llm.with_structured_output.call_args_list
            if call.args[0] is ProjectConfig
        ]
        assert len(project_config_calls) >= 1

    def test_add_local_runs_full_pipeline(
        self, runner, portfolio_dir, project_dir
    ):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            with patch(
                "autofolio.ingest.confirm_config",
                side_effect=lambda c: c,
            ):
                result = runner.invoke(main, [
                    "add",
                    str(project_dir),
                    "--portfolio-path", str(portfolio_dir),
                    "--no-profile",
                ])
        assert result.exit_code == 0
        schemas = [
            call.args[0]
            for call in mock_llm.with_structured_output.call_args_list
        ]
        assert ProjectConfig in schemas
        assert AnalysisResponse in schemas
        assert GenerationResponse in schemas

    def test_add_with_describe_dry_run(self, runner, portfolio_dir):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            with patch(
                "autofolio.ingest.confirm_config",
                side_effect=lambda c: c,
            ):
                result = runner.invoke(main, [
                    "add",
                    "--describe",
                    "A weather dashboard using React and D3",
                    "--portfolio-path", str(portfolio_dir),
                    "--no-profile",
                ])
        assert result.exit_code == 0, (
            f"Expected exit code 0 but got {result.exit_code}.\n"
            f"Exception: {result.exception}"
        )

    def test_add_confirm_cancel_exits_cleanly(
        self, runner, portfolio_dir, project_dir
    ):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            with patch(
                "autofolio.ingest.confirm_config",
                return_value=None,
            ):
                result = runner.invoke(main, [
                    "add",
                    str(project_dir),
                    "--portfolio-path", str(portfolio_dir),
                    "--no-profile",
                ])
        assert result.exit_code == 0

    def test_add_does_not_modify_portfolio_in_dry_run(
        self, runner, portfolio_dir, project_dir
    ):
        original = (portfolio_dir / "data" / "projects.json").read_text()
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            with patch(
                "autofolio.ingest.confirm_config",
                side_effect=lambda c: c,
            ):
                result = runner.invoke(main, [
                    "add",
                    str(project_dir),
                    "--portfolio-path", str(portfolio_dir),
                    "--no-profile",
                ])
        assert result.exit_code == 0
        after = (portfolio_dir / "data" / "projects.json").read_text()
        assert original == after


class TestErrorPaths:

    def test_run_missing_portfolio_flag(self, runner, config_file):
        result = runner.invoke(main, [
            "run",
            "--config", str(config_file),
        ])
        assert result.exit_code == 1

    def test_run_both_portfolio_flags(
        self, runner, portfolio_dir, config_file
    ):
        result = runner.invoke(main, [
            "run",
            "--config", str(config_file),
            "--portfolio-path", str(portfolio_dir),
            "--portfolio-url", "https://github.com/user/portfolio",
        ])
        assert result.exit_code == 1

    def test_run_invalid_config_json(self, runner, portfolio_dir, tmp_path):
        bad_config = tmp_path / "bad.json"
        bad_config.write_text("not valid json {{{")
        result = runner.invoke(main, [
            "run",
            "--config", str(bad_config),
            "--portfolio-path", str(portfolio_dir),
            "--no-profile",
        ])
        assert result.exit_code != 0

    def test_run_config_missing_required_fields(
        self, runner, portfolio_dir, tmp_path
    ):
        incomplete = tmp_path / "incomplete.json"
        incomplete.write_text(json.dumps({"title": "Only Title"}))
        result = runner.invoke(main, [
            "run",
            "--config", str(incomplete),
            "--portfolio-path", str(portfolio_dir),
            "--no-profile",
        ])
        assert result.exit_code != 0

    def test_run_no_config_option(self, runner):
        result = runner.invoke(main, ["run"])
        assert result.exit_code == 2

    def test_run_config_file_not_found(self, runner, portfolio_dir):
        result = runner.invoke(main, [
            "run",
            "--config", "/nonexistent/path/to/config.json",
            "--portfolio-path", str(portfolio_dir),
        ])
        assert result.exit_code == 2

    def test_add_no_source_provided(self, runner, portfolio_dir):
        result = runner.invoke(main, [
            "add",
            "--portfolio-path", str(portfolio_dir),
        ])
        assert result.exit_code == 1

    def test_add_missing_portfolio_flag(self, runner, project_dir):
        result = runner.invoke(main, [
            "add",
            str(project_dir),
        ])
        assert result.exit_code == 1

    def test_add_both_portfolio_flags(
        self, runner, portfolio_dir, project_dir
    ):
        result = runner.invoke(main, [
            "add",
            str(project_dir),
            "--portfolio-path", str(portfolio_dir),
            "--portfolio-url", "https://github.com/user/portfolio",
        ])
        assert result.exit_code == 1

    def test_run_empty_config_file(self, runner, portfolio_dir, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("{}")
        result = runner.invoke(main, [
            "run",
            "--config", str(empty),
            "--portfolio-path", str(portfolio_dir),
            "--no-profile",
        ])
        assert result.exit_code != 0

    def test_add_invalid_repo_path(self, runner, portfolio_dir):
        mock_llm = _make_mock_llm()
        with patch("autofolio.cli.get_llm", return_value=mock_llm):
            with patch(
                "autofolio.ingest.confirm_config",
                side_effect=lambda c: c,
            ):
                result = runner.invoke(main, [
                    "add",
                    "/nonexistent/project/path",
                    "--portfolio-path", str(portfolio_dir),
                    "--no-profile",
                ])
        assert result.exit_code != 0
