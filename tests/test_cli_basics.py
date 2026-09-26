from click.testing import CliRunner

from lima_ai import __version__
from lima_ai.cli import cli


def test_version_flag_prints_package_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_lima_ai_error_is_printed_with_step_and_exit_1(monkeypatch):
    from lima_ai import cli as cli_module
    from lima_ai.errors import LimaAiError

    @cli_module.cli.command("explode")
    def explode():
        raise LimaAiError("clone", "limactl clone failed", "disk full")

    try:
        result = CliRunner().invoke(cli, ["explode"])
    finally:
        cli_module.cli.commands.pop("explode")
    assert result.exit_code == 1
    assert "error [clone]: limactl clone failed" in result.output
    assert "disk full" in result.output
