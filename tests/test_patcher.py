from __future__ import annotations

from pathlib import Path

import pytest

from autofolio.config import PatchAction
from autofolio.patcher import PatchError, apply_patches


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


def _write(base: Path, rel: str, content: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestCreate:
    def test_creates_new_file(self, repo: Path) -> None:
        patches = [PatchAction(path="projects/new.md", action="create", content="# New Project\n")]
        result = apply_patches(repo, patches)
        assert len(result) == 1
        assert (repo / "projects" / "new.md").read_text() == "# New Project\n"

    def test_rejects_existing_file(self, repo: Path) -> None:
        _write(repo, "exists.md", "old")
        patches = [PatchAction(path="exists.md", action="create", content="new")]
        with pytest.raises(PatchError, match="already exists"):
            apply_patches(repo, patches)


class TestReplace:
    def test_replaces_file(self, repo: Path) -> None:
        _write(repo, "page.tsx", "old content")
        patches = [PatchAction(path="page.tsx", action="replace", content="new content")]
        apply_patches(repo, patches)
        assert (repo / "page.tsx").read_text() == "new content"

    def test_rejects_missing_file(self, repo: Path) -> None:
        patches = [PatchAction(path="missing.tsx", action="replace", content="x")]
        with pytest.raises(PatchError, match="not found"):
            apply_patches(repo, patches)


class TestAppend:
    def test_appends_content(self, repo: Path) -> None:
        _write(repo, "list.md", "# Projects\n")
        patches = [PatchAction(path="list.md", action="append", content="\n- New entry\n")]
        apply_patches(repo, patches)
        text = (repo / "list.md").read_text()
        assert text == "# Projects\n\n- New entry\n"

    def test_rejects_missing_file(self, repo: Path) -> None:
        patches = [PatchAction(path="nope.md", action="append", content="x")]
        with pytest.raises(PatchError, match="not found"):
            apply_patches(repo, patches)


class TestInsertAfterLine:
    def test_inserts_after_marker(self, repo: Path) -> None:
        _write(repo, "data.ts", 'const projects = [\n  { name: "A" },\n];\n')
        patches = [
            PatchAction(
                path="data.ts",
                action="insert_after_line",
                insert_after_marker='{ name: "A" },',
                content='  { name: "B" },',
            )
        ]
        apply_patches(repo, patches)
        text = (repo / "data.ts").read_text()
        assert '{ name: "B" },' in text
        lines = text.splitlines()
        idx_a = next(i for i, l in enumerate(lines) if '{ name: "A" }' in l)
        idx_b = next(i for i, l in enumerate(lines) if '{ name: "B" }' in l)
        assert idx_b == idx_a + 1

    def test_rejects_missing_marker(self, repo: Path) -> None:
        _write(repo, "file.txt", "line 1\nline 2\n")
        patches = [
            PatchAction(
                path="file.txt",
                action="insert_after_line",
                insert_after_marker="NOPE",
                content="new line",
            )
        ]
        with pytest.raises(PatchError, match="Marker not found"):
            apply_patches(repo, patches)

    def test_rejects_missing_marker_field(self, repo: Path) -> None:
        _write(repo, "file.txt", "hello\n")
        patches = [
            PatchAction(
                path="file.txt",
                action="insert_after_line",
                content="new",
            )
        ]
        with pytest.raises(PatchError, match="insert_after_marker"):
            apply_patches(repo, patches)


class TestSafety:
    def test_rejects_absolute_path(self, repo: Path) -> None:
        patches = [PatchAction(path="/etc/passwd", action="create", content="x")]
        with pytest.raises(PatchError, match="relative"):
            apply_patches(repo, patches)

    def test_rejects_path_traversal(self, repo: Path) -> None:
        patches = [PatchAction(path="../../etc/passwd", action="create", content="x")]
        with pytest.raises(PatchError, match="escapes repo root"):
            apply_patches(repo, patches)

    def test_rejects_unknown_action(self, repo: Path) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PatchAction(path="file.txt", action="delete", content="x")
