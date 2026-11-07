import tomllib

from click.testing import CliRunner

from lima_ai.cli import cli


def test_config_prints_effective_settings(env):
    result = env.invoke(["config"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0].startswith("# ")
    assert tomllib.loads(result.output)["vm"]["cpus"] == 4


def test_config_with_a_broken_file_is_a_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "lima-ai").mkdir()
    (tmp_path / "lima-ai/config.toml").write_text("cpus = \n")
    result = CliRunner().invoke(cli, ["config"])
    assert result.exit_code == 1
    assert "error [config]:" in result.output
    assert "Traceback" not in result.output


def test_config_edit_opens_the_editor_on_the_config_file(env, monkeypatch):
    editor = env.tmp_path / "ed"
    editor.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" > "$(dirname "$0")/opened"\n')
    editor.chmod(0o755)
    monkeypatch.setenv("VISUAL", str(editor))
    result = env.invoke(["config", "--edit"])
    assert result.exit_code == 0, result.output
    assert (env.tmp_path / "opened").read_text().strip() == str(env.tmp_path / "config/lima-ai/config.toml")
