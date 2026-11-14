import tomllib
from pathlib import Path

import pytest

from lima_ai.config import Config, load_config, save_setting
from lima_ai.config_file import edit, effective_toml, template_toml
from lima_ai.errors import LimaAiError


def test_effective_toml_of_defaults_parses_and_round_trips(tmp_path):
    path = tmp_path / "absent.toml"
    text = effective_toml(load_config(path), path)
    assert text.splitlines()[0] == f"# {path} (not found; showing defaults)"
    data = tomllib.loads(text)
    assert data["vm"] == {"cpus": 4, "memory": "8GiB", "disk": "60GiB", "ubuntu_release": "26.04"}
    assert data["versions"]["rtk"] == "0.49.0"
    assert data["developer_dir"] == "~/Developer"
    assert "ssh_keys" not in data["sync"] and "# ssh_keys is unset" in text
    assert "hook" not in data["base"] and "# hook is unset" in text


def test_effective_toml_shows_file_values_and_escapes_strings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[sync]\nextra_excludes = ['a\"b', 'c\\d']\nssh_keys = true\n[base]\nhook = \"/tmp/h.sh\"\n")
    text = effective_toml(load_config(path), path)
    assert text.splitlines()[0] == f"# {path}"
    data = tomllib.loads(text)
    assert data["sync"]["extra_excludes"] == ['a"b', "c\\d"]
    assert data["sync"]["ssh_keys"] is True
    assert data["base"]["hook"] == "/tmp/h.sh"


def test_template_toml_is_all_comments_under_live_headers(tmp_path):
    text = template_toml()
    data = tomllib.loads(text)
    assert data == {"vm": {}, "versions": {}, "sync": {}, "base": {}}
    assert "# cpus = 4" in text and '# hook = "~/lima/custom.sh"' in text
    assert "# ssh_keys = false" in text


def test_template_toml_then_save_setting_fills_the_existing_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(template_toml())
    save_setting("base", "hook", "/tmp/h.sh", path)
    assert path.read_text().count("[base]") == 1
    assert load_config(path).base.hook == Path("/tmp/h.sh")


def test_edit_creates_the_template_then_opens_the_editor(tmp_path, monkeypatch):
    editor = tmp_path / "ed"
    # The editor uncomments a line and changes its value, the way the template invites.
    editor.write_text('#!/bin/sh\nsed \'s/^# cpus = 4/cpus = 2/\' "$1" > "$1.new" && mv "$1.new" "$1"\n')
    editor.chmod(0o755)
    monkeypatch.setenv("VISUAL", str(editor))
    path = tmp_path / "cfg/config.toml"
    edit(path)
    assert path.read_text().startswith("# lima-ai settings.")
    assert load_config(path).vm.cpus == 2


def test_edit_reports_an_invalid_result_and_keeps_the_file(tmp_path, monkeypatch):
    editor = tmp_path / "ed"
    editor.write_text("#!/bin/sh\necho 'cpus = ' > \"$1\"\n")
    editor.chmod(0o755)
    monkeypatch.setenv("VISUAL", str(editor))
    path = tmp_path / "config.toml"
    with pytest.raises(LimaAiError) as excinfo:
        edit(path)
    assert excinfo.value.step == "config"
    assert path.read_text() == "cpus = \n"


def test_edit_without_a_working_editor_is_a_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("VISUAL", str(tmp_path / "missing-editor"))
    with pytest.raises(LimaAiError) as excinfo:
        edit(tmp_path / "config.toml")
    assert excinfo.value.step == "config"
    assert "check $VISUAL or $EDITOR" in excinfo.value.message


def test_edit_with_an_editor_that_exits_non_zero_says_so(tmp_path, monkeypatch):
    editor = tmp_path / "ed"
    editor.write_text("#!/bin/sh\nexit 1\n")
    editor.chmod(0o755)
    monkeypatch.setenv("VISUAL", str(editor))
    with pytest.raises(LimaAiError) as excinfo:
        edit(tmp_path / "config.toml")
    assert excinfo.value.message.startswith("editor failed (")
    assert "could not open" not in excinfo.value.message


def test_effective_toml_shows_the_hook_with_a_tilde(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[base]\nhook = "~/lima/custom.sh"\n')
    text = effective_toml(load_config(path), path)
    assert 'hook = "~/lima/custom.sh"' in text


def test_hooks_show_as_unset_and_in_the_template(tmp_path):
    text = effective_toml(Config(), tmp_path / "config.toml")
    assert "# hooks is unset" in text and "hooks_skipped = []" in text
    assert '# hooks = ["~/.claude/hooks/check.sh"]' in template_toml()
