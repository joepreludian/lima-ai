import contextlib
import dataclasses
import json
import re
import tempfile

from lima_ai.config import SyncConfig, config_dir, state_dir
from tests.conftest import GUEST_HOME
from tests.fakes import lima_list

INSTANCE = "dev-myapp-feat-a"
WORKDIR = f"{GUEST_HOME}/work/myapp"
CREATED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def base_then_clone(env, clone_status="Running"):
    """limactl list: only dev-base on the first call, dev-base + the clone afterwards."""
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped"), (INSTANCE, clone_status)))
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped")), times=1)


def existing(env, status="Running"):
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped"), (INSTANCE, status)))


def index_of(commands, prefix):
    return next(i for i, c in enumerate(commands) if c.startswith(prefix))


OPENSSH_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\n"


def with_ssh_keys(env, *names):
    ssh = env.home / ".ssh"
    ssh.mkdir()
    (ssh / "known_hosts").write_text("github.com ssh-ed25519 AAAA\n")
    (ssh / "config").write_text("Host github.com\n")
    for name in names:
        (ssh / name).write_text(OPENSSH_KEY)


def keep_git_staging(env, monkeypatch):
    """Make the git staging dir outlive the push so tests can look inside it."""
    staging = env.tmp_path / "git-staging"
    real = tempfile.TemporaryDirectory

    @contextlib.contextmanager
    def fake_tempdir(prefix):
        if not prefix.startswith("lima-ai-git-"):
            with real(prefix=prefix) as tmp:
                yield tmp
            return
        staging.mkdir()
        yield str(staging)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", fake_tempdir)
    return staging


def staged_ssh_names(staging):
    ssh = staging / ".ssh"
    return sorted(p.name for p in ssh.iterdir()) if ssh.exists() else []


def set_ssh_keys(env, value):
    env.cfg = dataclasses.replace(env.cfg, sync=SyncConfig(ssh_keys=value))


def saved_config():
    return (config_dir() / "config.toml").read_text()


# --- new -------------------------------------------------------------------


def test_new_runs_every_step_in_order(env):
    env.write_token()
    base_then_clone(env)
    result = env.invoke(["new", "preludian/myapp", "feat_a", "--branch", "feat/a"])
    assert result.exit_code == 0, result.output
    cmds = env.runner.commands
    order = [
        index_of(cmds, f"limactl clone --tty=false dev-base {INSTANCE}"),
        index_of(cmds, f"limactl start --tty=false {INSTANCE}"),
        index_of(cmds, f"limactl shell {INSTANCE} bash -c 'umask 077"),
        index_of(cmds, "rsync -a --copy-unsafe-links"),
        index_of(cmds, f"rsync -a -e 'ssh -F /Users/jon/.lima/{INSTANCE}/ssh.config' /"),
        index_of(cmds, f"limactl shell {INSTANCE} mkdir -p {WORKDIR}"),
        index_of(cmds, "rsync -a --stats --exclude-from="),
        index_of(cmds, f"limactl shell {INSTANCE} git -C {WORKDIR} switch -c feat/a"),
    ]
    assert order == sorted(order)


def test_new_sends_token_over_stdin_only(env):
    env.write_token("sk-ant-oat01-secret")
    base_then_clone(env)
    env.invoke(["new", "preludian/myapp", "feat-a"])
    assert not any("sk-ant-oat01-secret" in c for c in env.runner.commands)
    token_calls = [c for c in env.runner.calls if c.input and "CLAUDE_CODE_OAUTH_TOKEN" in c.input]
    assert len(token_calls) == 1
    assert token_calls[0].input == "export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-secret\n"
    assert "~/.config/lima-ai/env" in token_calls[0].command


def test_new_copies_project_into_guest_workdir(env):
    env.write_token()
    base_then_clone(env)
    env.invoke(["new", "preludian/myapp", "feat-a"])
    project = next(c for c in env.runner.commands if "--exclude-from=" in c)
    assert project.endswith(f"{env.cfg.developer_dir}/preludian/myapp/ lima-{INSTANCE}:work/myapp/")
    exclude_file = state_dir() / "rsync-exclude.txt"
    assert "node_modules/" in exclude_file.read_text()


def test_new_passes_resource_overrides_to_clone(env):
    env.write_token()
    base_then_clone(env)
    env.invoke(["new", "preludian/myapp", "feat-a", "--cpus", "2", "--memory", "4GiB", "--disk", "80GiB"])
    assert f"limactl clone --tty=false dev-base {INSTANCE} --cpus 2 --memory 4 --disk 80" in env.runner.commands


def test_new_prints_summary_with_mdns_and_ip_but_no_url(env):
    env.write_token()
    base_then_clone(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert f"lima-{INSTANCE}.local" in result.output
    assert "192.168.64.8" in result.output
    assert "http://" not in result.output
    assert "lima-ai shell preludian/myapp feat-a" in result.output


def info_script_pushes(env):
    return [c for c in env.runner.calls if c.input and "hostname" in c.input and "lima-ai-info" in c.command]


def test_new_installs_the_guest_info_script(env):
    env.write_token()
    base_then_clone(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    pushes = info_script_pushes(env)
    assert len(pushes) == 1
    assert pushes[0].argv[:3] == ["limactl", "shell", INSTANCE]
    assert "~/.local/bin/lima-ai-info" in pushes[0].command
    assert "chmod 755" in pushes[0].command


def test_new_records_instance_for_list(env):
    env.write_token()
    base_then_clone(env)
    env.invoke(["new", "preludian/myapp", "feat-a"])
    record = json.loads((state_dir() / f"instances/{INSTANCE}.json").read_text())
    assert record.keys() == {"project", "slug", "workspace", "created_at"}
    assert (record["project"], record["slug"], record["workspace"]) == ("preludian/myapp", "myapp", "feat-a")
    assert CREATED_AT.fullmatch(record["created_at"])


def test_new_creates_backups_dir(env):
    env.write_token()
    base_then_clone(env)
    env.invoke(["new", "preludian/myapp", "feat-a"])
    assert env.cfg.backups_dir.is_dir()


def test_new_warns_when_ssh_agent_has_no_key(env):
    env.write_token()
    base_then_clone(env)
    env.runner.on("ssh-add -l", returncode=1, stdout="The agent has no identities.\n")
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0
    assert "ssh-agent" in result.output


def test_new_without_token_asks_for_auth_before_cloning(env):
    base_then_clone(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert "lima-ai auth" in result.output
    assert not env.runner.find("limactl clone")


def test_new_without_base_asks_for_base(env):
    env.write_token()
    env.runner.on("limactl list --json", "")
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert "lima-ai base" in result.output


def test_new_with_running_base_is_refused(env):
    env.write_token()
    env.runner.on("limactl list --json", lima_list(("dev-base", "Running")))
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert "limactl stop dev-base" in result.output
    assert not env.runner.find("limactl clone")


def test_new_with_existing_instance_is_refused(env):
    env.write_token()
    existing(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert "already exists" in result.output
    assert not env.runner.find("limactl clone")


def test_new_with_missing_project_is_refused(env):
    env.write_token()
    base_then_clone(env)
    result = env.invoke(["new", "preludian/nope", "feat-a"])
    assert result.exit_code == 1
    assert not env.runner.find("limactl clone")


def test_new_with_bad_memory_fails_before_cloning(env):
    env.write_token()
    base_then_clone(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--memory", "lots"])
    assert result.exit_code == 1
    assert not env.runner.find("limactl clone")


def test_new_failure_after_clone_keeps_vm_and_suggests_next_steps(env):
    env.write_token()
    base_then_clone(env)
    env.runner.on("--exclude-from=", returncode=23, stderr="rsync error")
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert "error [sync]" in result.output
    assert f"{INSTANCE} is kept" in result.output
    assert "lima-ai sync preludian/myapp feat-a" in result.output
    assert "lima-ai destroy preludian/myapp feat-a" in result.output
    assert not env.runner.find("limactl delete")


# --- sync / sync-claude / shell / start / stop ------------------------------------


def test_sync_on_clean_guest_runs_without_asking(env):
    existing(env)
    result = env.invoke(["sync", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert env.runner.find("--exclude-from=")
    assert "overwrit" in result.output


def test_sync_on_dirty_guest_asks_and_aborts_on_no(env):
    existing(env)
    env.runner.on("status --porcelain", " M app.py\n")
    result = env.invoke(["sync", "preludian/myapp", "feat-a"], input="n\n")
    assert result.exit_code == 1
    assert "app.py" in result.output
    assert not env.runner.find("--exclude-from=")


def test_sync_on_dirty_guest_proceeds_on_yes(env):
    existing(env)
    env.runner.on("status --porcelain", " M app.py\n")
    result = env.invoke(["sync", "preludian/myapp", "feat-a"], input="y\n")
    assert result.exit_code == 0
    assert env.runner.find("--exclude-from=")


def test_sync_needs_running_vm(env):
    existing(env, status="Stopped")
    result = env.invoke(["sync", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert "lima-ai start preludian/myapp feat-a" in result.output


def test_sync_claude_pushes_token_claude_and_git(env):
    env.write_token()
    existing(env)
    result = env.invoke(["sync-claude", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert [c for c in env.runner.calls if c.input and "CLAUDE_CODE_OAUTH_TOKEN" in c.input]
    assert env.runner.find("--copy-unsafe-links")
    assert not env.runner.find("--exclude-from=")
    assert len(info_script_pushes(env)) == 1


# --- SSH private keys ---------------------------------------------------------------


def test_sync_claude_asks_before_copying_keys_and_remembers_yes(env, monkeypatch):
    env.write_token()
    existing(env)
    with_ssh_keys(env, "id_ed25519", "work.key")
    staging = keep_git_staging(env, monkeypatch)
    result = env.invoke(["sync-claude", "preludian/myapp", "feat-a"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "id_ed25519, work.key" in result.output
    assert staged_ssh_names(staging) == ["id_ed25519", "known_hosts", "work.key"]
    assert saved_config() == "[sync]\nssh_keys = true\n"
    assert str(config_dir() / "config.toml") in result.output


def test_sync_claude_remembers_no_and_keeps_keys_out(env, monkeypatch):
    env.write_token()
    existing(env)
    with_ssh_keys(env, "id_ed25519")
    staging = keep_git_staging(env, monkeypatch)
    result = env.invoke(["sync-claude", "preludian/myapp", "feat-a"], input="n\n")
    assert result.exit_code == 0, result.output
    assert staged_ssh_names(staging) == ["known_hosts"]
    assert saved_config() == "[sync]\nssh_keys = false\n"


def test_sync_claude_default_answer_is_no(env, monkeypatch):
    env.write_token()
    existing(env)
    with_ssh_keys(env, "id_ed25519")
    staging = keep_git_staging(env, monkeypatch)
    result = env.invoke(["sync-claude", "preludian/myapp", "feat-a"], input="\n")
    assert result.exit_code == 0, result.output
    assert staged_ssh_names(staging) == ["known_hosts"]
    assert saved_config() == "[sync]\nssh_keys = false\n"


def test_sync_claude_follows_a_saved_yes_without_asking(env, monkeypatch):
    env.write_token()
    existing(env)
    with_ssh_keys(env, "id_ed25519")
    set_ssh_keys(env, True)
    staging = keep_git_staging(env, monkeypatch)
    result = env.invoke(["sync-claude", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert "[y/N]" not in result.output
    assert staged_ssh_names(staging) == ["id_ed25519", "known_hosts"]
    assert not (config_dir() / "config.toml").exists()


def test_sync_claude_follows_a_saved_no_without_asking(env, monkeypatch):
    env.write_token()
    existing(env)
    with_ssh_keys(env, "id_ed25519")
    set_ssh_keys(env, False)
    staging = keep_git_staging(env, monkeypatch)
    result = env.invoke(["sync-claude", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert "[y/N]" not in result.output
    assert staged_ssh_names(staging) == ["known_hosts"]


def test_sync_claude_does_not_ask_when_there_are_no_keys(env, monkeypatch):
    env.write_token()
    existing(env)
    with_ssh_keys(env)
    result = env.invoke(["sync-claude", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert "[y/N]" not in result.output
    assert not (config_dir() / "config.toml").exists()


def test_new_asks_about_keys_before_cloning(env, monkeypatch):
    env.write_token()
    base_then_clone(env)
    with_ssh_keys(env, "id_ed25519")
    staging = keep_git_staging(env, monkeypatch)
    result = env.invoke(["new", "preludian/myapp", "feat-a"], input="y\n")
    assert result.exit_code == 0, result.output
    assert result.output.index("[y/N]") < result.output.index("Cloning dev-base")
    assert staged_ssh_names(staging) == ["id_ed25519", "known_hosts"]
    assert saved_config() == "[sync]\nssh_keys = true\n"


def test_shell_opens_interactive_shell_in_workdir(env):
    existing(env)
    result = env.invoke(["shell", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0
    call = env.runner.find(f"limactl shell --workdir {WORKDIR} {INSTANCE}")[0]
    assert call.argv[-1] == INSTANCE
    assert call.interactive


def test_start_and_stop(env):
    existing(env, status="Stopped")
    assert env.invoke(["start", "preludian/myapp", "feat-a"]).exit_code == 0
    assert f"limactl start --tty=false {INSTANCE}" in env.runner.commands
    assert env.invoke(["stop", "preludian/myapp", "feat-a"]).exit_code == 0
    assert f"limactl stop {INSTANCE}" in env.runner.commands


def test_commands_on_unknown_vm_say_so(env):
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped")))
    result = env.invoke(["stop", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert f"no VM named {INSTANCE}" in result.output


def test_commands_work_after_host_project_folder_is_gone(env):
    existing(env, status="Stopped")
    result = env.invoke(["start", "preludian/deleted", "feat-a"])
    assert result.exit_code == 1
    assert "no VM named dev-deleted-feat-a" in result.output


# --- list ---------------------------------------------------------------------------


def three_vms(env):
    env.runner.on(
        "limactl list --json",
        lima_list(
            ("dev-base", "Stopped"), (INSTANCE, "Running"), ("dev-other-thing-b", "Stopped"), ("default", "Running")
        ),
    )
    env.runner.on(f"limactl shell {INSTANCE} git -C {WORKDIR} rev-parse HEAD", "0123456789abcdef\n")
    env.runner.on(f"limactl shell {INSTANCE} git -C {WORKDIR} symbolic-ref -q --short HEAD", "feat-a-work\n")
    (state_dir() / "instances").mkdir(parents=True)
    (state_dir() / f"instances/{INSTANCE}.json").write_text(
        json.dumps({"project": "preludian/myapp", "slug": "myapp", "workspace": "feat-a"})
    )


def test_list_shows_project_workspace_status_branch_and_fqdn(env):
    three_vms(env)
    result = env.invoke(["list"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split() == ["PROJECT", "WORKSPACE", "STATUS", "BRANCH", "FQDN"]
    assert lines[1].split() == ["preludian/myapp", "feat-a", "Running", "feat-a-work", f"lima-{INSTANCE}.local"]
    assert lines[2].split() == ["?", "other-thing-b", "Stopped", "-", "lima-dev-other-thing-b.local"]
    assert len(lines) == 3


def test_list_reads_records_written_before_the_workspace_rename(env):
    three_vms(env)
    (state_dir() / f"instances/{INSTANCE}.json").write_text(
        json.dumps({"project": "preludian/myapp", "slug": "myapp", "feat": "feat-a"})
    )
    result = env.invoke(["list"])
    assert result.output.splitlines()[1].split()[:2] == ["preludian/myapp", "feat-a"]


def test_list_does_not_shell_into_stopped_vms(env):
    three_vms(env)
    env.invoke(["list"])
    assert not env.runner.find("limactl shell dev-other-thing-b")


def test_list_shows_no_branch_when_the_workdir_is_not_a_repository(env):
    three_vms(env)
    env.runner.on(f"limactl shell {INSTANCE} git -C {WORKDIR} rev-parse HEAD", "", returncode=128)
    result = env.invoke(["list"])
    assert result.output.splitlines()[1].split()[3] == "-"


def test_ls_is_an_alias_for_list(env):
    three_vms(env)
    assert env.invoke(["ls"]).output == env.invoke(["list"]).output


def test_list_with_no_vms(env):
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped")))
    result = env.invoke(["list"])
    assert result.exit_code == 0
    assert "no workspace VMs" in result.output
    assert "lima-ai new" in result.output


# --- rm ---------------------------------------------------------------------------


def test_rm_clean_running_vm_with_yes_deletes_without_asking(env):
    existing(env)
    env.runner.on("@{u}..", "")
    result = env.invoke(["destroy", "preludian/myapp", "feat-a", "--yes"])
    assert result.exit_code == 0, result.output
    assert f"limactl delete -f {INSTANCE}" in env.runner.commands


def test_rm_asks_once_without_yes(env):
    existing(env)
    result = env.invoke(["destroy", "preludian/myapp", "feat-a"], input="n\n")
    assert result.exit_code == 1
    assert not env.runner.find("limactl delete")


def test_rm_dirty_vm_asks_second_confirmation_even_with_yes(env):
    existing(env)
    env.runner.on("status --porcelain", "?? notes.txt\n")
    result = env.invoke(["destroy", "preludian/myapp", "feat-a", "--yes"], input="n\n")
    assert result.exit_code == 1
    assert "notes.txt" in result.output
    assert not env.runner.find("limactl delete")
    result = env.invoke(["destroy", "preludian/myapp", "feat-a", "--yes"], input="y\n")
    assert result.exit_code == 0
    assert env.runner.find("limactl delete")


def test_rm_unpushed_commits_without_upstream_checks_all_local_commits(env):
    existing(env)
    env.runner.on("@{u}..", returncode=128, stderr="fatal: no upstream configured")
    env.runner.on("log --oneline HEAD --not --remotes", "abc123 wip: login form\n")
    result = env.invoke(["destroy", "preludian/myapp", "feat-a", "--yes"], input="n\n")
    assert result.exit_code == 1
    assert "abc123 wip: login form" in result.output
    assert not env.runner.find("limactl delete")


def test_rm_force_skips_both_confirmations(env):
    existing(env)
    env.runner.on("status --porcelain", " M app.py\n")
    result = env.invoke(["destroy", "preludian/myapp", "feat-a", "--force"])
    assert result.exit_code == 0, result.output
    assert env.runner.find("limactl delete")


def test_rm_stopped_vm_cannot_check_work_and_asks_once(env):
    existing(env, status="Stopped")
    result = env.invoke(["destroy", "preludian/myapp", "feat-a"], input="y\n")
    assert result.exit_code == 0
    assert "stopped" in result.output
    assert not env.runner.find("status --porcelain")
    assert env.runner.find("limactl delete")


def test_rm_missing_workdir_is_not_unsaved_work(env):
    existing(env)
    env.runner.on(f"test -d {WORKDIR}", returncode=1)
    result = env.invoke(["destroy", "preludian/myapp", "feat-a", "--yes"])
    assert result.exit_code == 0, result.output
    assert env.runner.find("limactl delete")


def test_rm_forgets_instance_record(env):
    existing(env)
    (state_dir() / "instances").mkdir(parents=True)
    record = state_dir() / f"instances/{INSTANCE}.json"
    record.write_text("{}")
    env.invoke(["destroy", "preludian/myapp", "feat-a", "--yes"])
    assert not record.exists()


def git_positions(env, host: tuple[str, str], guest: tuple[str, str]) -> None:
    host_repo = env.cfg.developer_dir / "preludian/myapp"
    env.runner.on(f"git -C {host_repo} symbolic-ref -q --short HEAD", host[0] + "\n")
    env.runner.on(f"git -C {host_repo} rev-parse HEAD", host[1] + "\n")
    env.runner.on(f"git -C {WORKDIR} symbolic-ref -q --short HEAD", guest[0] + "\n")
    env.runner.on(f"git -C {WORKDIR} rev-parse HEAD", guest[1] + "\n")


def test_sync_asks_when_vm_repo_has_moved_away_from_hosts(env):
    existing(env)
    git_positions(env, host=("main", "a" * 40), guest=("feat/a", "b" * 40))
    result = env.invoke(["sync", "preludian/myapp", "feat-a"], input="n\n")
    assert result.exit_code == 1
    assert "feat/a" in result.output and "main" in result.output
    assert "HEAD" in result.output
    assert not env.runner.find("--exclude-from=")


def test_sync_does_not_ask_when_vm_repo_matches_hosts(env):
    existing(env)
    git_positions(env, host=("main", "a" * 40), guest=("main", "a" * 40))
    result = env.invoke(["sync", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert env.runner.find("--exclude-from=")


def test_sync_skips_the_git_check_when_host_project_is_not_a_repo(env):
    existing(env)
    host_repo = env.cfg.developer_dir / "preludian/myapp"
    env.runner.on(f"git -C {host_repo} rev-parse HEAD", returncode=128, stderr="fatal: not a git repository")
    env.runner.on(f"git -C {WORKDIR} rev-parse HEAD", "b" * 40 + "\n")
    result = env.invoke(["sync", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert env.runner.find("--exclude-from=")
