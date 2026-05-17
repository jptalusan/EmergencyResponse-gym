"""Unit tests for utilities."""

from __future__ import annotations

import pytest

from utils.config_validator import load_cfg, resolve_config_dir


def test_resolve_config_dir_accepts_absolute_and_relative_paths(tmp_path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    assert resolve_config_dir(str(config_dir)) == config_dir.resolve()

    monkeypatch.chdir(tmp_path)
    assert resolve_config_dir("configs") == config_dir.resolve()

    with pytest.raises(FileNotFoundError, match="Config directory not found"):
        resolve_config_dir("missing")


def test_load_cfg_composes_hydra_config_from_directory(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("seed: 123\nname: test-config\n")

    cfg = load_cfg(str(config_dir), "config")

    assert cfg.seed == 123
    assert cfg.name == "test-config"


def test_resolve_config_dir_falls_back_to_basename_in_current_working_directory(tmp_path, monkeypatch):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    assert resolve_config_dir("does/not/exist/configs") == config_dir.resolve()


def test_resolve_config_dir_accepts_path_like_input(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    assert resolve_config_dir(config_dir) == config_dir.resolve()


def test_resolve_config_dir_rejects_absolute_file_path(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("seed: 1\n")

    with pytest.raises(FileNotFoundError) as exc:
        resolve_config_dir(str(config_file))

    assert "Config directory not found" in str(exc.value)
    assert str(config_file.resolve()) in str(exc.value)


def test_resolve_config_dir_error_lists_relative_candidates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError) as exc:
        resolve_config_dir("missing/nested/configs")

    message = str(exc.value)
    assert "missing/nested/configs" in message
    assert str((tmp_path / "missing/nested/configs").resolve()) in message
    assert str((tmp_path / "configs").resolve()) in message


def test_load_cfg_supports_nested_config_values(tmp_path):
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "\n".join(
            [
                "seed: 321",
                "city:",
                "  name: nashville",
                "  geography:",
                "    h3_resolution: 8",
            ]
        )
        + "\n"
    )

    cfg = load_cfg(config_dir, "config")

    assert cfg.seed == 321
    assert cfg.city.name == "nashville"
    assert cfg.city.geography.h3_resolution == 8


def test_load_cfg_raises_when_config_name_is_missing(tmp_path):
    from hydra.errors import MissingConfigException

    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    with pytest.raises(MissingConfigException):
        load_cfg(str(config_dir), "missing")
