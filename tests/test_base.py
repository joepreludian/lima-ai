import pytest

from lima_ai.base import build
from lima_ai.config import Config
from lima_ai.errors import LimaAiError
from tests.fakes import FakeRunner, lima_list


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return Config(developer_dir=tmp_path / "Developer", backups_dir=tmp_path / "Developer/backups/docker")


def test_fresh_build_starts_verifies_seals_and_stops(cfg, tmp_path):
    runner = FakeRunner()
    build(cfg, runner, rebuild=False)
    template = tmp_path / "state/lima-ai/base/dev-base.yaml"
    assert template.is_file()
    assert cfg.backups_dir.is_dir()
    commands = [c for c in runner.commands if not c.startswith("limactl list")]
    assert commands[0] == f"limactl start --name dev-base --tty=false {template}"
    assert commands[1].startswith("limactl shell dev-base bash -c ")
    assert "hello-world" in commands[1]
    assert commands[2].startswith("limactl shell dev-base sudo bash -c ")
    assert "machine-id" in commands[2]
    assert commands[3] == "limactl stop dev-base"
    assert len(commands) == 4


def test_existing_base_without_rebuild_is_an_error(cfg):
    runner = FakeRunner().on("limactl list --json", lima_list(("dev-base", "Stopped")))
    with pytest.raises(LimaAiError) as excinfo:
        build(cfg, runner, rebuild=False)
    assert "--rebuild" in excinfo.value.message
    assert not runner.find("limactl start")


def test_rebuild_deletes_existing_base_first(cfg):
    runner = FakeRunner().on("limactl list --json", lima_list(("dev-base", "Running")))
    build(cfg, runner, rebuild=True)
    delete = runner.commands.index("limactl delete -f dev-base")
    start = next(i for i, c in enumerate(runner.commands) if c.startswith("limactl start"))
    assert delete < start


def test_failed_verification_leaves_vm_running_unsealed(cfg):
    runner = FakeRunner().on("hello-world", returncode=1, stderr="--> node -v\nnode: not found")
    with pytest.raises(LimaAiError) as excinfo:
        build(cfg, runner, rebuild=False)
    assert excinfo.value.step == "verify-base"
    assert "left running" in excinfo.value.message
    assert "node: not found" in excinfo.value.stderr_tail
    assert not runner.find("sudo bash")
    assert not runner.find("limactl stop")
