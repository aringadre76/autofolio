from __future__ import annotations

from pathlib import Path

import pytest

from autofolio.validator import BuildError, run_build


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


class TestRunBuild:
    def test_empty_commands_passes(self, repo: Path) -> None:
        assert run_build(repo, []) is True

    def test_successful_command(self, repo: Path) -> None:
        assert run_build(repo, ["true"]) is True

    def test_failing_command_raises(self, repo: Path) -> None:
        with pytest.raises(BuildError, match="failed"):
            run_build(repo, ["false"])

    def test_multiple_commands_stop_on_failure(self, repo: Path) -> None:
        marker = repo / "marker.txt"
        with pytest.raises(BuildError):
            run_build(repo, ["false", f"touch {marker}"])
        assert not marker.exists()

    def test_multiple_commands_all_pass(self, repo: Path) -> None:
        marker = repo / "marker.txt"
        assert run_build(repo, ["true", f"touch {marker}"]) is True
        assert marker.exists()
