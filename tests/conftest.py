import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from lima_ai.cli import App, cli
from lima_ai.config import Config
from tests.fakes import FakeRunner

GUEST_HOME = "/home/jon.linux"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated host: config/state dirs, a Developer dir with a project, a home with ~/.claude."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # Commands check that limactl and rsync are installed; FakeRunner answers
    # every call, so these stubs only have to exist (and fail if ever run).
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for tool in ("limactl", "rsync"):
        (stubs / tool).write_text("#!/bin/sh\necho 'stub: not for running' >&2\nexit 99\n")
        (stubs / tool).chmod(0o755)
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ['PATH']}")
    developer = tmp_path / "Developer"
    (developer / "preludian/myapp").mkdir(parents=True)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/CLAUDE.md").write_text("# rules\n")
    cfg = Config(developer_dir=developer, backups_dir=developer / "backups/docker")
    return Env(tmp_path=tmp_path, cfg=cfg, home=home)


class Env:
    def __init__(self, tmp_path: Path, cfg: Config, home: Path) -> None:
        self.tmp_path = tmp_path
        self.cfg = cfg
        self.home = home
        self.runner = FakeRunner()
        self.runner.on("printenv HOME", GUEST_HOME + "\n")
        self.runner.on("rsync --version", "openrsync: protocol version 29\n")
        self.runner.on("ip -4 -o addr show lima0", "3: lima0    inet 192.168.64.8/24 metric 100 brd 192.168.64.255\n")

    def invoke(self, args: list[str], input: str | None = None):
        app = App(runner=self.runner, config=self.cfg, home=self.home)
        return CliRunner().invoke(cli, args, input=input, obj=app)

    def write_token(self, token: str = "sk-ant-oat01-secret") -> None:
        from lima_ai.auth import write_token

        write_token(token)
