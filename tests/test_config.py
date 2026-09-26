from pathlib import Path

import pytest

from lima_ai.config import Config, config_dir, load_config, state_dir
from lima_ai.errors import LimaAiError


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "absent.toml")
    home = Path.home()
    assert cfg.developer_dir == home / "Developer"
    assert cfg.backups_dir == home / "Developer/backups/docker"
    assert cfg.app_port == 8002
    assert (cfg.vm.cpus, cfg.vm.memory, cfg.vm.disk, cfg.vm.ubuntu_release) == (4, "8GiB", "60GiB", "26.04")
    assert cfg.versions.node_major == 24
    assert cfg.versions.rtk == "0.49.0"
    assert cfg.versions.rtk_sha256 == "c8ea4b6560841e73157c134fd4a3293914c6ede42e786ee985cf491fde691ba7"
    assert cfg.versions.docker_backup == "0.4.0"
    assert cfg.versions.docker_backup_sha256 == "9c7bdf7c25d4f8c19253a3ffd73bfd34e2d8d4f6e1cd7736b27feffbee8a22d8"
    assert cfg.sync.extra_excludes == ()


def test_toml_overrides_top_level_and_sections(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            """
app_port = 3000
[vm]
cpus = 8
memory = "16GiB"
[sync]
extra_excludes = ["*.sqlite", "tmp/"]
""",
        )
    )
    assert cfg.app_port == 3000
    assert cfg.vm.cpus == 8
    assert cfg.vm.memory == "16GiB"
    assert cfg.vm.disk == "60GiB"
    assert cfg.sync.extra_excludes == ("*.sqlite", "tmp/")


def test_paths_expand_tilde(tmp_path):
    cfg = load_config(write(tmp_path, 'developer_dir = "~/code"\nbackups_dir = "~/bk"\n'))
    assert cfg.developer_dir == Path.home() / "code"
    assert cfg.backups_dir == Path.home() / "bk"


@pytest.mark.parametrize(
    "text, key",
    [
        ("colour = 1\n", "colour"),
        ("[vm]\ngpus = 1\n", "vm.gpus"),
        ("[network]\nx = 1\n", "network"),
    ],
)
def test_unknown_keys_are_an_error(tmp_path, text, key):
    with pytest.raises(LimaAiError) as excinfo:
        load_config(write(tmp_path, text))
    assert excinfo.value.step == "config"
    assert f"unknown key '{key}'" in excinfo.value.message


@pytest.mark.parametrize(
    "text",
    ['app_port = "8002"\n', "[vm]\ncpus = true\n", "[vm]\nmemory = 8\n", "[sync]\nextra_excludes = \"x\"\n"],
)
def test_wrong_value_types_are_an_error(tmp_path, text):
    with pytest.raises(LimaAiError) as excinfo:
        load_config(write(tmp_path, text))
    assert excinfo.value.step == "config"


def test_section_given_as_scalar_is_an_error(tmp_path):
    with pytest.raises(LimaAiError):
        load_config(write(tmp_path, "vm = 4\n"))


def test_invalid_toml_names_the_file(tmp_path):
    path = write(tmp_path, "app_port = \n")
    with pytest.raises(LimaAiError) as excinfo:
        load_config(path)
    assert str(path) in excinfo.value.message


def test_config_and_state_dirs_default_under_home(monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert config_dir() == Path.home() / ".config/lima-ai"
    assert state_dir() == Path.home() / ".local/state/lima-ai"


def test_config_and_state_dirs_follow_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    assert config_dir() == tmp_path / "cfg/lima-ai"
    assert state_dir() == tmp_path / "st/lima-ai"


def test_default_config_path_is_in_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "lima-ai").mkdir()
    (tmp_path / "lima-ai/config.toml").write_text("app_port = 9000\n")
    assert load_config().app_port == 9000


def test_config_is_a_frozen_value():
    assert isinstance(load_config(Path("/nonexistent/config.toml")), Config)
