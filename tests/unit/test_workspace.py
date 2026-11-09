from pathlib import Path

import pytest

from practicum.workspace import ROOT_ENV_VAR, WorkspaceNotFoundError, find_root


def test_find_root_walks_upward(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ROOT_ENV_VAR, raising=False)
    nested = fake_repo / "labs" / "m01-lab1" / "starter" / "app"
    assert find_root(nested) == fake_repo.resolve()


def test_find_root_defaults_to_cwd(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ROOT_ENV_VAR, raising=False)
    monkeypatch.chdir(fake_repo / "docs")
    assert find_root() == fake_repo.resolve()


def test_env_override_wins(
    fake_repo: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(fake_repo))
    assert find_root(tmp_path_factory.mktemp("elsewhere")) == fake_repo.resolve()


def test_invalid_env_override_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(tmp_path))
    with pytest.raises(WorkspaceNotFoundError, match="is not a practicum repository"):
        find_root()


def test_pixi_toml_without_labs_is_not_a_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ROOT_ENV_VAR, raising=False)
    (tmp_path / "pixi.toml").write_text("", encoding="utf-8")
    with pytest.raises(WorkspaceNotFoundError, match="no practicum repository"):
        find_root(tmp_path)
