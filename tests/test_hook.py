import os
from pathlib import Path

import pytest

from lima_ai.config import BaseConfig, Config
from lima_ai.errors import LimaAiError
from lima_ai.hook import display_path, resolve, write_starter


def test_resolve_without_flag_or_config_is_none(tmp_path):
    assert resolve(Config(), None) is None


def test_flag_path_is_resolved_absolute_and_marked_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "custom.sh").write_text("echo hi\n")
    hook = resolve(Config(), "custom.sh")
    assert hook.path == tmp_path / "custom.sh"
    assert hook.path.is_absolute()
    assert hook.source == "flag"
    assert hook.content == "echo hi\n"


def test_missing_flag_path_is_a_short_error(tmp_path):
    with pytest.raises(LimaAiError) as excinfo:
        resolve(Config(), str(tmp_path / "nope.sh"))
    assert excinfo.value.step == "base"
    assert excinfo.value.message == f"hook {tmp_path / 'nope.sh'} not found"


def test_saved_hook_is_used_when_no_flag(tmp_path):
    (tmp_path / "h.sh").write_text("true\n")
    hook = resolve(Config(base=BaseConfig(hook=tmp_path / "h.sh")), None)
    assert hook.source == "config"


def test_missing_saved_hook_names_the_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    with pytest.raises(LimaAiError) as excinfo:
        resolve(Config(base=BaseConfig(hook=tmp_path / "gone.sh")), None)
    assert "saved in" in excinfo.value.message
    assert "lima-ai config --edit" in excinfo.value.message
    assert "--use-hook PATH" in excinfo.value.message


def test_flag_wins_over_a_missing_saved_hook(tmp_path):
    (tmp_path / "other.sh").write_text("true\n")
    hook = resolve(Config(base=BaseConfig(hook=tmp_path / "gone.sh")), str(tmp_path / "other.sh"))
    assert hook.path == tmp_path / "other.sh"


def test_write_starter_creates_parents_and_refuses_overwrite(tmp_path):
    target = tmp_path / "deep/dir/custom.sh"
    assert write_starter(target) == target
    assert target.stat().st_mode & 0o777 == 0o644
    assert target.read_text().startswith("#!/bin/bash")
    with pytest.raises(LimaAiError) as excinfo:
        write_starter(target)
    assert "exists" in excinfo.value.message


def test_display_path_collapses_home():
    assert display_path(Path.home() / "lima/custom.sh") == "~/lima/custom.sh"
    assert display_path(Path("/opt/x.sh")) == "/opt/x.sh"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files regardless of their mode")
def test_unreadable_hook_is_rejected_before_anything_runs(tmp_path):
    path = tmp_path / "locked.sh"
    path.write_text("true\n")
    path.chmod(0)
    try:
        with pytest.raises(LimaAiError) as excinfo:
            resolve(Config(), str(path))
    finally:
        path.chmod(0o644)
    assert excinfo.value.step == "base"
    assert excinfo.value.message.startswith(f"hook {path} not readable (")


def test_hook_content_is_a_snapshot_taken_at_resolve_time(tmp_path):
    path = tmp_path / "h.sh"
    path.write_text("echo one\n")
    hook = resolve(Config(), str(path))
    path.write_text("echo two\n")
    assert hook.content == "echo one\n"
