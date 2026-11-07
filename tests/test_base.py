import pytest

from lima_ai.base import banner, build
from lima_ai.config import Config
from lima_ai.errors import LimaAiError
from lima_ai.hook import Hook
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


HOOK_TEXT = 'apt-get install -y openjdk-21-jdk-headless\necho "it\'s $HOME"\n'


@pytest.fixture
def hook(tmp_path):
    path = tmp_path / "custom.sh"
    path.write_text(HOOK_TEXT)
    return Hook(path=path, source="flag")


def test_hook_runs_as_root_in_the_guest_home_between_start_and_verify(cfg, hook):
    runner = FakeRunner().on("printenv HOME", "/home/jon.linux\n")
    build(cfg, runner, rebuild=False, hook=hook)
    commands = [c for c in runner.calls if not c.command.startswith("limactl list")]
    assert commands[0].command.startswith("limactl start")
    assert commands[1].command == "limactl shell dev-base printenv HOME"
    hook_call = commands[2]
    assert hook_call.argv[:6] == ["limactl", "shell", "--workdir", "/home/jon.linux", "dev-base", "sudo"]
    assert hook_call.argv[6:] == ["bash", "-c", HOOK_TEXT]
    assert hook_call.interactive is True
    assert "hello-world" in commands[3].command
    assert commands[-1].command == "limactl stop dev-base"


def test_failed_hook_stops_the_build_and_leaves_the_vm_running(cfg, hook):
    runner = FakeRunner().on("openjdk-21", returncode=3)
    with pytest.raises(LimaAiError) as excinfo:
        build(cfg, runner, rebuild=False, hook=hook)
    assert excinfo.value.step == "hook"
    assert excinfo.value.message == (
        f"hook {hook.path} failed (exit 3). dev-base is left running for inspection: limactl shell dev-base"
    )
    assert excinfo.value.stderr_tail == ""
    assert not runner.find("hello-world")
    assert not runner.find("limactl stop")


def test_existing_base_refusal_mentions_a_saved_flag_hook(cfg, hook):
    runner = FakeRunner().on("limactl list --json", lima_list(("dev-base", "Stopped")))
    with pytest.raises(LimaAiError) as excinfo:
        build(cfg, runner, rebuild=False, hook=hook)
    assert "hook saved: lima-ai base --rebuild will use" in excinfo.value.message
    with pytest.raises(LimaAiError) as excinfo:
        build(cfg, runner, rebuild=False, hook=Hook(path=hook.path, source="config"))
    assert "hook saved" not in excinfo.value.message


def test_banner_names_the_hook_source_and_the_logs(hook, monkeypatch):
    monkeypatch.delenv("LIMA_HOME", raising=False)
    text = banner(rebuild=True, hook=hook)
    lines = text.splitlines()
    assert len({len(line) for line in lines}) == 1  # a straight box
    assert "lima-ai base --use-hook" in text and "--rebuild" in text
    assert "(from --use-hook, saved to config.toml)" in text
    assert "~/.lima/dev-base/" in text
    assert "limactl shell dev-base" in text
    assert "(from config.toml)" in banner(rebuild=False, hook=Hook(path=hook.path, source="config"))
    none = banner(rebuild=False, hook=None)
    assert "hook:  none (lima-ai base --init-hook PATH writes a starter)" in none
    assert none.splitlines()[1].strip(" │|").strip() == "lima-ai base"


def test_banner_follows_lima_home(hook, monkeypatch):
    monkeypatch.setenv("LIMA_HOME", "/Volumes/vm/lima")
    assert "/Volumes/vm/lima/dev-base/" in banner(rebuild=False, hook=hook)


def test_banner_is_printed_before_anything_is_deleted(cfg, hook, capsys):
    runner = FakeRunner().on("limactl list --json", lima_list(("dev-base", "Stopped")))
    build(cfg, runner, rebuild=True, hook=hook)
    err = capsys.readouterr().err
    assert err.index("hook:") < err.index("==> Deleting the old dev-base")
    assert "==> Running hook" in err
