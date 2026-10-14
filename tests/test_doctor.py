import json
import os

import pytest
from click.testing import CliRunner

from lima_ai import doctor
from lima_ai.auth import write_token
from lima_ai.cli import App, cli
from tests.fakes import FakeRunner

TOOLS = ("limactl", "rsync", "claude", "ssh-add", "docker-backup")


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A healthy macOS host: every tool on PATH, a token, a stopped dev-base."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in TOOLS:
        (bin_dir / tool).write_text("#!/bin/sh\nexit 99\n")
        (bin_dir / tool).chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    write_token("sk-ant-oat01-secret")
    runner = FakeRunner()
    runner.on("limactl --version", "limactl version 2.2.1\n")
    runner.on("docker-backup --version", "docker-backup 0.4.0\n")
    runner.on("ssh-add -l", "256 SHA256:abc jon@mac (ED25519)\n")
    runner.on("limactl list --json", base_json("Stopped"))
    return Host(bin_dir, runner)


class Host:
    def __init__(self, bin_dir, runner):
        self.bin_dir = bin_dir
        self.runner = runner

    def remove(self, tool):
        os.remove(self.bin_dir / tool)

    def checks(self, system="Darwin", machine="arm64"):
        return {c.name: c for c in doctor.run_checks(self.runner, system=system, machine=machine)}


def base_json(status):
    return json.dumps({"name": "dev-base", "status": status, "dir": "/x", "sshConfigFile": "/x/ssh.config"}) + "\n"


def test_healthy_mac_passes_every_check(host):
    checks = host.checks()
    assert {c.status for c in checks.values()} == {"ok"}
    assert checks["limactl (>= 2.0)"].detail == "2.2.1"
    assert checks["ssh-agent key"].detail == "1 key"


@pytest.mark.parametrize(
    ("system", "machine", "status"),
    [("Darwin", "arm64", "ok"), ("Darwin", "x86_64", "ok"), ("Linux", "x86_64", "ok"), ("Windows", "AMD64", "fail")],
)
def test_platform(host, system, machine, status):
    assert host.checks(system, machine)["platform"].status == status


def test_rosetta_is_skipped_off_apple_silicon(host):
    assert host.checks("Linux", "aarch64")["Rosetta"].status == "skip"
    assert host.checks("Darwin", "x86_64")["Rosetta"].status == "skip"
    assert not host.runner.find("arch -x86_64")


def test_rosetta_missing_fails_with_install_hint(host):
    host.runner.on("arch -x86_64", returncode=1)
    check = host.checks()["Rosetta"]
    assert check.status == "fail"
    assert "softwareupdate --install-rosetta" in check.fix


@pytest.mark.parametrize("tool", ["limactl", "rsync", "claude"])
def test_missing_required_tool_fails(host, tool):
    host.remove(tool)
    check = next(c for name, c in host.checks().items() if name.startswith(tool))
    assert check.status == "fail"
    assert check.fix


def test_old_limactl_fails(host):
    host.runner.on("limactl --version", "limactl version 1.2.0\n")
    check = host.checks()["limactl (>= 2.0)"]
    assert check.status == "fail"
    assert check.detail == "1.2.0"


def test_missing_limactl_skips_dev_base(host):
    host.remove("limactl")
    assert host.checks()["dev-base"].status == "skip"


def test_ssh_agent_without_keys_fails(host):
    host.runner.on("ssh-add -l", "The agent has no identities.\n", returncode=1)
    check = host.checks()["ssh-agent key"]
    assert check.status == "fail"
    assert "ssh-add" in check.fix


def test_broken_config_fails(host, tmp_path):
    (tmp_path / "config/lima-ai/config.toml").write_text("app_port = [\n")
    check = host.checks()["config.toml"]
    assert check.status == "fail"
    assert "config.toml" in check.fix


def test_missing_token_fails(host, tmp_path):
    (tmp_path / "config/lima-ai/oauth-token").unlink()
    check = host.checks()["Claude token"]
    assert check.status == "fail"
    assert check.fix == "lima-ai auth"


def test_dev_base_missing_warns(host):
    host.runner.on("limactl list --json", "")
    check = host.checks()["dev-base"]
    assert check.status == "warn"
    assert check.fix == "lima-ai base"


def test_dev_base_running_warns(host):
    host.runner.on("limactl list --json", base_json("Running"))
    check = host.checks()["dev-base"]
    assert check.status == "warn"
    assert "limactl stop dev-base" in check.fix


def test_docker_backup_missing_or_old_only_warns(host):
    host.runner.on("docker-backup --version", "docker-backup 0.3.9\n")
    assert host.checks()["docker-backup (>= 0.4.0)"].status == "warn"
    host.remove("docker-backup")
    assert host.checks()["docker-backup (>= 0.4.0)"].status == "warn"


def test_render_without_problems_has_no_fix_table():
    out = doctor.render([doctor.Check("rsync", "ok")])
    assert "rsync" in out
    assert "Fix" not in out
    assert "All checks passed." in out


def test_render_lists_problems_with_their_fixes():
    out = doctor.render(
        [
            doctor.Check("rsync", "ok"),
            doctor.Check("Claude token", "fail", fix="lima-ai auth"),
            doctor.Check("dev-base", "warn", fix="lima-ai base"),
        ]
    )
    status_table, fix_table = out.split("Problem")
    assert "lima-ai auth" not in status_table
    assert "Claude token" in fix_table and "lima-ai auth" in fix_table
    assert "dev-base" in fix_table and "lima-ai base" in fix_table
    assert "1 problem, 1 warning." in out


def run_doctor(host):
    return CliRunner().invoke(cli, ["doctor"], obj=App(runner=host.runner))


def test_doctor_command_exits_0_when_only_warnings(host, monkeypatch):
    monkeypatch.setattr(doctor.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(doctor.platform, "machine", lambda: "arm64")
    host.remove("docker-backup")
    result = run_doctor(host)
    assert result.exit_code == 0, result.output
    assert "0 problems, 1 warning." in result.output


def test_doctor_command_exits_1_on_failure(host, monkeypatch):
    monkeypatch.setattr(doctor.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(doctor.platform, "machine", lambda: "arm64")
    host.remove("rsync")
    result = run_doctor(host)
    assert result.exit_code == 1
    assert "1 problem" in result.output
