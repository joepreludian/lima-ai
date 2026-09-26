import pytest
from click.testing import CliRunner

from lima_ai.auth import read_token, token_path, write_token
from lima_ai.cli import App, cli
from lima_ai.errors import LimaAiError
from tests.fakes import FakeRunner


@pytest.fixture(autouse=True)
def config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_token_path_is_in_config_dir(config_home):
    assert token_path() == config_home / "lima-ai/oauth-token"


def test_write_then_read_round_trip_with_mode_600():
    write_token("sk-ant-oat01-abc\n")
    assert read_token() == "sk-ant-oat01-abc"
    assert token_path().stat().st_mode & 0o777 == 0o600


def test_overwriting_a_loose_file_tightens_its_mode():
    token_path().parent.mkdir(parents=True)
    token_path().write_text("old")
    token_path().chmod(0o644)
    write_token("new-token")
    assert token_path().stat().st_mode & 0o777 == 0o600
    assert read_token() == "new-token"


@pytest.mark.parametrize("bad", ["", "   \n", "two words", "a\nb"])
def test_malformed_tokens_are_rejected(bad):
    with pytest.raises(LimaAiError):
        write_token(bad)


def test_missing_token_points_to_auth():
    with pytest.raises(LimaAiError) as excinfo:
        read_token()
    assert "lima-ai auth" in excinfo.value.message


def test_auth_from_stdin_writes_token_without_running_claude():
    runner = FakeRunner()
    result = CliRunner().invoke(cli, ["auth", "--from-stdin"], input="sk-ant-oat01-xyz\n", obj=App(runner=runner))
    assert result.exit_code == 0, result.output
    assert read_token() == "sk-ant-oat01-xyz"
    assert runner.calls == []
    assert "sk-ant-oat01-xyz" not in result.output


def test_auth_runs_setup_token_interactively_then_prompts_hidden():
    runner = FakeRunner()
    result = CliRunner().invoke(cli, ["auth"], input="sk-ant-oat01-typed\n", obj=App(runner=runner))
    assert result.exit_code == 0, result.output
    assert runner.commands == ["claude setup-token"]
    assert runner.calls[0].interactive
    assert read_token() == "sk-ant-oat01-typed"
    assert "sk-ant-oat01-typed" not in result.output
