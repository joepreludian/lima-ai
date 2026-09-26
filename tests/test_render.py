import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from lima_ai.config import Config, SyncConfig, VmConfig, load_config
from lima_ai.render import (
    PROVISION,
    guest_script,
    render_base,
    render_env,
    render_template,
    rsync_excludes,
)


@pytest.fixture
def cfg() -> Config:
    return load_config(Path("/nonexistent/config.toml"))


def test_template_is_valid_yaml_without_jinja_or_lima_placeholders(cfg):
    text = render_template(cfg)
    assert "{{" not in text and "{%" not in text
    assert isinstance(yaml.safe_load(text), dict)


def test_template_core_settings(cfg):
    doc = yaml.safe_load(render_template(cfg))
    assert doc["minimumLimaVersion"] == "2.0.0"
    assert doc["base"] == ["template:_images/ubuntu-26.04"]
    assert doc["vmType"] == "vz"
    assert (doc["cpus"], doc["memory"], doc["disk"]) == (4, "8GiB", "60GiB")
    assert doc["vmOpts"]["vz"]["rosetta"] == {"enabled": True, "binfmt": True}
    assert doc["networks"] == [{"vzNAT": True}]
    assert doc["mountType"] == "virtiofs"
    assert doc["containerd"] == {"system": False, "user": False}
    assert doc["ssh"]["forwardAgent"] is True


def test_every_port_forward_to_host_localhost_is_ignored(cfg):
    doc = yaml.safe_load(render_template(cfg))
    assert doc["portForwards"] == [{"guestIP": "0.0.0.0", "guestPortRange": [1, 65535], "proto": "any", "ignore": True}]


def test_mounts_developer_dir_read_only_and_backups_writable(cfg):
    doc = yaml.safe_load(render_template(cfg))
    assert doc["mounts"] == [
        {"location": str(cfg.developer_dir), "writable": False},
        {"location": str(cfg.backups_dir), "mountPoint": "/backups/docker", "writable": True},
    ]


def test_vm_and_path_config_flow_into_template(tmp_path):
    cfg = Config(
        developer_dir=tmp_path / "dev dir",
        backups_dir=tmp_path / "bk",
        vm=VmConfig(cpus=2, memory="4GiB", disk="30GiB", ubuntu_release="24.04"),
    )
    doc = yaml.safe_load(render_template(cfg))
    assert doc["base"] == ["template:_images/ubuntu-24.04"]
    assert (doc["cpus"], doc["memory"], doc["disk"]) == (2, "4GiB", "30GiB")
    assert doc["mounts"][0]["location"] == str(tmp_path / "dev dir")


def test_provision_entries_in_order_with_modes(cfg):
    doc = yaml.safe_load(render_template(cfg))
    entries = [(p["mode"], p["file"]["url"]) for p in doc["provision"]]
    assert entries == [
        ("system", "provision/10-system.sh"),
        ("system", "provision/20-docker.sh"),
        ("user", "provision/30-node.sh"),
        ("user", "provision/40-rust.sh"),
        ("user", "provision/50-claude.sh"),
        ("user", "provision/60-rtk.sh"),
        ("system", "provision/70-docker-backup.sh"),
    ]
    assert [name for name, _ in PROVISION] == [url.removeprefix("provision/") for _, url in entries]


def test_render_base_writes_template_and_every_referenced_script(cfg, tmp_path):
    dest = tmp_path / "base"
    yaml_path = render_base(cfg, dest)
    assert yaml_path == dest / "dev-base.yaml"
    doc = yaml.safe_load(yaml_path.read_text())
    for entry in doc["provision"]:
        script = dest / entry["file"]["url"]
        assert script.is_file()
        text = script.read_text()
        assert text.startswith("#!/bin/bash\n")
        assert "set -euo pipefail" in text
        assert "{{" not in text and "{%" not in text
    assert not list(dest.rglob("*.j2"))


def test_render_base_replaces_stale_files(cfg, tmp_path):
    dest = tmp_path / "base"
    (dest / "provision").mkdir(parents=True)
    (dest / "provision/99-stale.sh").write_text("old")
    render_base(cfg, dest)
    assert not (dest / "provision/99-stale.sh").exists()


def test_provision_scripts_check_and_write_their_markers(cfg, tmp_path):
    render_base(cfg, tmp_path)
    for name, mode in PROVISION:
        text = (tmp_path / "provision" / name).read_text()
        step = name.removesuffix(".sh")
        marker_dir = "/var/lib/lima-ai" if mode == "system" else "$HOME/.local/state/lima-ai"
        assert f'marker="{marker_dir}/{step}.done"' in text
        assert '[ -e "$marker" ] && exit 0' in text
        assert text.rstrip().endswith('touch "$marker"')


def test_pinned_versions_and_checksums_are_rendered(cfg, tmp_path):
    render_base(cfg, tmp_path)
    rtk = (tmp_path / "provision/60-rtk.sh").read_text()
    assert "releases/download/v0.49.0/" in rtk
    assert "rtk-aarch64-unknown-linux-gnu.tar.gz" in rtk
    assert cfg.versions.rtk_sha256 in rtk
    assert "sha256sum -c" in rtk
    backup = (tmp_path / "provision/70-docker-backup.sh").read_text()
    assert "releases/download/v0.4.0/" in backup
    assert "docker-backup-0.4.0-aarch64-unknown-linux-musl" in backup
    assert cfg.versions.docker_backup_sha256 in backup
    assert "sha256sum -c" in backup
    node = (tmp_path / "provision/30-node.sh").read_text()
    assert "fnm install 24" in node


def test_system_script_configures_avahi_for_lima0(cfg, tmp_path):
    render_base(cfg, tmp_path)
    text = (tmp_path / "provision/10-system.sh").read_text()
    for package in ["avahi-daemon", "libnss-mdns", "ripgrep", "rsync", "build-essential"]:
        assert package in text
    assert "allow-interfaces=lima0" in text
    assert "use-ipv6=no" in text


def test_system_script_closes_chronys_udp_command_port(cfg, tmp_path):
    # Lima forwards UDP listeners that exist when its agent connects to host
    # ports despite the ignore rule; chronyd's localhost:323 is the only one.
    render_base(cfg, tmp_path)
    text = (tmp_path / "provision/10-system.sh").read_text()
    assert "cmdport 0" in text
    assert "/etc/chrony/conf.d/" in text


def test_claude_script_sets_up_shell_and_onboarding(cfg, tmp_path):
    render_base(cfg, tmp_path)
    text = (tmp_path / "provision/50-claude.sh").read_text()
    assert "hasCompletedOnboarding" in text
    assert "alias cc='claude --dangerously-skip-permissions'" in text
    assert ".config/lima-ai/env" in text


def test_guest_scripts_are_available(cfg):
    verify = guest_script("verify-base.sh")
    for check in [
        "hello-world",
        "node -v",
        "cargo -V",
        "claude --version",
        "rtk --version",
        "docker compose version",
        "docker-backup --version",
        "docker-backup doctor",
        "avahi-daemon --check",
    ]:
        assert check in verify
    seal = guest_script("seal-base.sh")
    for step in [
        "docker system prune -af",
        "/etc/machine-id",
        "/var/lib/dbus/machine-id",
        "/etc/ssh/ssh_host_",
        "ssh-keygen -A",
        "apt-get clean",
    ]:
        assert step in seal


def test_rsync_excludes_default_list_plus_extras(tmp_path):
    cfg = Config(sync=SyncConfig(extra_excludes=("*.sqlite",)))
    lines = rsync_excludes(cfg).splitlines()
    for pattern in [
        "node_modules/",
        "target/",
        ".venv/",
        "venv/",
        "__pycache__/",
        "dist/",
        "build/",
        ".next/",
        ".nuxt/",
        ".turbo/",
        ".cache/",
        ".DS_Store",
    ]:
        assert pattern in lines
    assert lines[-1] == "*.sqlite"
    assert ".git/" not in lines and not any(line.startswith(".env") for line in lines)


def test_env_file_exports_quoted_token():
    assert render_env("sk-ant-oat01-abc") == "export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-abc\n"
    assert render_env("a'b c") == "export CLAUDE_CODE_OAUTH_TOKEN='a'\"'\"'b c'\n"


@pytest.mark.skipif(shutil.which("limactl") is None, reason="limactl not installed")
def test_rendered_template_passes_limactl_validate(cfg, tmp_path):
    yaml_path = render_base(cfg, tmp_path)
    result = subprocess.run(["limactl", "validate", str(yaml_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
