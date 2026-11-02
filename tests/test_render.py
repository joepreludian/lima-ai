import re
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
    render_instance_file,
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
    for package in ["avahi-daemon", "libnss-mdns", "ripgrep", "rsync", "build-essential", "fzf", "lazygit"]:
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


def test_claude_script_sets_up_the_shell(cfg, tmp_path):
    render_base(cfg, tmp_path)
    text = (tmp_path / "provision/50-claude.sh").read_text()
    assert "alias cc='claude --dangerously-skip-permissions'" in text
    assert ".config/lima-ai/env" in text
    # The installer creates ~/.claude.json itself, so onboarding is marked done per VM instead.
    assert ".claude.json" not in text


def test_claude_setup_script_marks_onboarding_done_and_wires_rtk():
    text = guest_script("lima-ai-claude-setup")
    assert "jq '.hasCompletedOnboarding = true'" in text
    assert "rtk init -g --auto-patch" in text
    assert "</dev/null" in text  # rtk must not read the script's stdin


def test_guest_scripts_are_available(cfg):
    verify = guest_script("verify-base.sh")
    for check in [
        "hello-world",
        "node -v",
        "cargo -V",
        "claude --version",
        "rtk --version",
        "rg --version",
        "fzf --version",
        "lazygit --version",
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


def test_instance_file_exports_shell_quoted_values():
    text = render_instance_file("clients/acme shop", "feat-a", "work/acme-shop", "2026-11-01T14:03:22Z")
    assert text == (
        "LIMA_AI_PROJECT='clients/acme shop'\n"
        "LIMA_AI_WORKSPACE=feat-a\n"
        "LIMA_AI_WORKDIR=work/acme-shop\n"
        "LIMA_AI_CREATED_AT=2026-11-01T14:03:22Z\n"
    )


def test_instance_file_round_trips_through_bash(tmp_path):
    """The file is sourced by lima-ai-info, so quoting must survive a project path with a quote in it."""
    path = tmp_path / "instance"
    path.write_text(render_instance_file("it's/here", "feat-a", "work/here", "unknown"))
    result = subprocess.run(
        ["bash", "-c", '. "$1" && printf "%s|%s" "$LIMA_AI_PROJECT" "$LIMA_AI_CREATED_AT"', "_", str(path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "it's/here|unknown"


def utf8_locale() -> str:
    """A UTF-8 locale this host has, so bash counts characters the way a terminal shows them."""
    known = subprocess.run(["locale", "-a"], capture_output=True, text=True).stdout.split()
    for name in ("C.UTF-8", "C.utf8", "en_US.UTF-8", "en_US.utf8"):
        if name in known:
            return name
    pytest.skip("no UTF-8 locale installed")


def guest_home(tmp_path, instance_file: bool = True, repo: str = "branch", project: str = "preludian/myapp"):
    """A throwaway guest HOME and a bin of stubs. repo: 'branch', 'detached', 'none' or 'parent' (HOME is the repo)."""
    home = tmp_path / "home"
    (home / ".config/lima-ai").mkdir(parents=True)
    if instance_file:
        (home / ".config/lima-ai/instance").write_text(
            f"LIMA_AI_PROJECT={project}\nLIMA_AI_WORKSPACE=feat-a\n"
            "LIMA_AI_WORKDIR=work/myapp\nLIMA_AI_CREATED_AT=2026-11-01T14:03:22Z\n"
        )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "hostname").write_text("#!/bin/sh\necho lima-dev-myapp-feat-a\n")
    (fake_bin / "ip").write_text(
        "#!/bin/sh\necho '3: lima0    inet 192.168.64.8/24 brd 192.168.64.255 scope global lima0'\n"
    )
    for stub in ("hostname", "ip"):
        (fake_bin / stub).chmod(0o755)
    workdir = home / "work/myapp"
    workdir.mkdir(parents=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(workdir)]
    if repo in ("branch", "detached"):
        subprocess.run([*git, "init", "-q", "-b", "feat-a"], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    if repo == "detached":
        subprocess.run([*git, "checkout", "-q", "--detach"], check=True)
    if repo == "parent":
        subprocess.run([*git[:-1], str(home), "init", "-q", "-b", "main"], check=True)
    return home, {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(home)}


def info_card(
    tmp_path,
    instance_file: bool = True,
    repo: str = "branch",
    project: str = "preludian/myapp",
    locale: str | None = None,
):
    """Run lima-ai-info under a throwaway HOME (see guest_home)."""
    _, env = guest_home(tmp_path, instance_file, repo, project)
    if locale:
        env["LC_ALL"] = locale
    return subprocess.run(["bash", "-c", guest_script("lima-ai-info")], env=env, capture_output=True, text=True)


def test_lima_ai_info_prints_the_card(tmp_path):
    result = info_card(tmp_path)
    assert result.returncode == 0, result.stderr
    # The longest row is the FQDN one (39 characters), so the box is 43 wide.
    assert result.stdout == (
        "+-----------------------------------------+\n"
        "| LIMA-AI - Instance Details              |\n"
        "+-----------------------------------------+\n"
        "| Project:    preludian/myapp             |\n"
        "| Workspace:  feat-a                      |\n"
        "| FQDN:       lima-dev-myapp-feat-a.local |\n"
        "| IP:         192.168.64.8                |\n"
        "| Created at: 2026-11-01T14:03:22Z        |\n"
        "| Git branch: feat-a                      |\n"
        "+-----------------------------------------+\n"
    )


def test_lima_ai_info_widens_the_box_to_the_longest_row(tmp_path):
    result = info_card(tmp_path, project="clients/a-rather-long-customer-name/their-application")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len({len(line) for line in lines}) == 1
    assert lines[3] == "| Project:    clients/a-rather-long-customer-name/their-application |"


def test_lima_ai_info_keeps_the_box_aligned_for_a_non_ascii_project(tmp_path):
    result = info_card(tmp_path, project="clientes/coração", locale=utf8_locale())
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len({len(line) for line in lines}) == 1
    assert lines[3] == "| Project:    clientes/coração            |"


def test_lima_ai_info_reports_detached_head(tmp_path):
    result = info_card(tmp_path, repo="detached")
    assert result.returncode == 0, result.stderr
    assert "Git branch: (detached HEAD)" in result.stdout


def test_lima_ai_info_reports_a_workdir_without_git(tmp_path):
    result = info_card(tmp_path, repo="none")
    assert result.returncode == 0, result.stderr
    assert "Git branch: no git repository" in result.stdout


def test_lima_ai_info_ignores_a_repository_above_the_workdir(tmp_path):
    result = info_card(tmp_path, repo="parent")
    assert result.returncode == 0, result.stderr
    assert "Git branch: no git repository" in result.stdout


def test_lima_ai_info_fails_clearly_without_an_instance_file(tmp_path):
    result = info_card(tmp_path, instance_file=False)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "no instance file; run lima-ai sync-claude from the host" in result.stderr


@pytest.mark.skipif(shutil.which("limactl") is None, reason="limactl not installed")
def test_rendered_template_passes_limactl_validate(cfg, tmp_path):
    yaml_path = render_base(cfg, tmp_path)
    result = subprocess.run(["limactl", "validate", str(yaml_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- lima-ai-prompt.sh ---------------------------------------------------------------

ANSI = re.compile("\x1b\\[[0-9;]*m|[\x01\x02]")


def prompt_session(tmp_path, commands: str, instance_file: bool = True, repo: str = "branch", ps1: str = "stock> "):
    """Feed commands to an interactive bash whose rc file is lima-ai-prompt.sh; return everything it printed.

    Interactive bash prints each expanded prompt to stderr even when stdin is a pipe, so the output
    holds the prompts as a user would see them, colors included.
    """
    home, env = guest_home(tmp_path, instance_file, repo)
    rc = tmp_path / "rc"
    rc.write_text(guest_script("lima-ai-prompt.sh"))
    env["PS1"] = ps1
    env["BASH_SILENCE_DEPRECATION_WARNING"] = "1"
    result = subprocess.run(
        ["bash", "--noediting", "--rcfile", str(rc), "-i"],
        input=commands,
        env=env,
        capture_output=True,
        text=True,
        cwd=home,
    )
    return result.stdout + result.stderr


def test_lima_ai_prompt_shows_vm_workspace_folder_and_branch(tmp_path):
    output = prompt_session(tmp_path, "cd ~/work/myapp\nexit\n")
    assert "l-ai lima-dev-myapp-feat-a.local feat-a ~/work/myapp (feat-a)$ exit" in ANSI.sub("", output)


def test_lima_ai_prompt_colors_every_segment(tmp_path):
    output = prompt_session(tmp_path, "cd ~/work/myapp\nexit\n")
    assert (
        "\x1b[1;33ml-ai\x1b[0m \x1b[36mlima-dev-myapp-feat-a.local\x1b[0m \x1b[1;35mfeat-a\x1b[0m "
        "\x1b[34m~/work/myapp\x1b[0m\x1b[32m (feat-a)\x1b[0m$ exit"
    ) in output.replace("\x01", "").replace("\x02", "")


def test_lima_ai_prompt_drops_the_branch_outside_a_repository(tmp_path):
    output = prompt_session(tmp_path, "cd ~\nexit\n", repo="none")
    assert "l-ai lima-dev-myapp-feat-a.local feat-a ~$ exit" in ANSI.sub("", output)


def test_lima_ai_prompt_shows_the_commit_when_head_is_detached(tmp_path):
    output = prompt_session(tmp_path, "cd ~/work/myapp\nexit\n", repo="detached")
    assert re.search(r"feat-a ~/work/myapp \([0-9a-f]{7,}\)\$ exit", ANSI.sub("", output))


def test_lima_ai_prompt_keeps_the_stock_prompt_without_an_instance_file(tmp_path):
    output = prompt_session(tmp_path, "exit\n", instance_file=False)
    assert "stock> exit" in output
    assert "l-ai" not in output


def test_prompt_install_script_adds_one_bashrc_line_however_often_it_runs(tmp_path):
    from lima_ai.instance import PROMPT_INSTALL_SCRIPT

    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("PS1='stock> '\n")
    for _ in range(2):
        subprocess.run(
            ["bash", "-c", PROMPT_INSTALL_SCRIPT],
            input="# prompt\n",
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
            check=True,
            text=True,
        )
    assert (home / ".config/lima-ai/prompt.sh").read_text() == "# prompt\n"
    bashrc = (home / ".bashrc").read_text()
    assert bashrc.startswith("PS1='stock> '\n")
    assert bashrc.count("# lima-ai prompt\n") == 1
    assert bashrc.count(". ~/.config/lima-ai/prompt.sh") == 1
