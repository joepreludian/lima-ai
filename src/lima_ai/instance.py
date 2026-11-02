import json
import shlex
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import click

from lima_ai import auth
from lima_ai.claude_config import push_claude_config
from lima_ai.config import Config, save_ssh_keys, state_dir
from lima_ai.errors import LimaAiError
from lima_ai.gitconfig import find_private_keys, push_git_config
from lima_ai.limactl import Instance, Limactl, gib
from lima_ai.naming import BASE_INSTANCE, project_dir, resolve
from lima_ai.render import guest_script, render_env, render_instance_file, rsync_excludes
from lima_ai.runner import Runner
from lima_ai.sync import progress_flags, project_argv

MAX_LISTED_COMMITS = 20


def note(message: str) -> None:
    click.echo(message, err=True)


class Workspace:
    """One workspace VM: its names, and the guest paths lima-ai works with."""

    def __init__(self, cfg: Config, runner: Runner, host_home: Path, project: str, workspace: str) -> None:
        self.cfg = cfg
        self.runner = runner
        self.host_home = host_home
        self.names = resolve(cfg.developer_dir, project, workspace)
        self.lima = Limactl(runner)
        self._guest_home: str | None = None

    @property
    def name(self) -> str:
        return self.names.instance

    def hint(self, command: str) -> str:
        """A command line the user can paste, so a project path with spaces is quoted."""
        return shlex.join(["lima-ai", command, self.names.project, self.names.workspace])

    def instance(self) -> Instance:
        instance = self.lima.get(self.name)
        if instance is None:
            raise LimaAiError("instance", f"no VM named {self.name}; create it with `{self.hint('new')}`")
        return instance

    def running_instance(self) -> Instance:
        instance = self.instance()
        if not instance.running:
            raise LimaAiError("instance", f"{self.name} is {instance.status}; start it with `{self.hint('start')}`")
        return instance

    @property
    def guest_home(self) -> str:
        if self._guest_home is None:
            self._guest_home = self.lima.home(self.name)
        return self._guest_home

    @property
    def workdir(self) -> str:
        return f"{self.guest_home}/{self.names.workdir}"

    def shell(self, argv: list[str], **kwargs):
        return self.lima.shell(self.name, argv, **kwargs)


# --- instance records (for `list`: instance names cannot be split back into slug and workspace)


def _record_path(name: str) -> Path:
    return state_dir() / "instances" / f"{name}.json"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(ws: Workspace, created_at: str) -> None:
    path = _record_path(ws.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ws.names
    data = {"project": names.project, "slug": names.slug, "workspace": names.workspace, "created_at": created_at}
    path.write_text(json.dumps(data) + "\n")


def lookup(name: str) -> dict | None:
    """The record for a VM, with the pre-0.5 `feat` key read as `workspace`."""
    path = _record_path(name)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    if "feat" in data:
        data["workspace"] = data.pop("feat")
    return data


def forget(name: str) -> None:
    _record_path(name).unlink(missing_ok=True)


# --- steps shared by new, sync and sync-claude


def push_token(ws: Workspace, token: str) -> None:
    """The token goes over stdin into a mode-600 file; it never appears in argv."""
    script = "umask 077 && mkdir -p ~/.config/lima-ai && cat > ~/.config/lima-ai/env && chmod 600 ~/.config/lima-ai/env"
    ws.shell(["bash", "-c", script], input=render_env(token), step="token")


def push_info_script(ws: Workspace) -> None:
    """Install lima-ai-info (prints the VM's connection card) into the guest's ~/.local/bin."""
    script = "mkdir -p ~/.local/bin && cat > ~/.local/bin/lima-ai-info && chmod 755 ~/.local/bin/lima-ai-info"
    ws.shell(["bash", "-c", script], input=guest_script("lima-ai-info"), step="guest tools")


# Writes the prompt file from stdin and sources it from ~/.bashrc, adding that line only once.
PROMPT_INSTALL_SCRIPT = (
    "mkdir -p ~/.config/lima-ai && cat > ~/.config/lima-ai/prompt.sh && "
    "{ grep -qF 'lima-ai/prompt.sh' ~/.bashrc 2>/dev/null || "
    "printf '\\n# lima-ai prompt\\n[ -f ~/.config/lima-ai/prompt.sh ] && . ~/.config/lima-ai/prompt.sh\\n'"
    " >> ~/.bashrc; }"
)


def push_prompt(ws: Workspace) -> None:
    """Install the l-ai bash prompt: ~/.config/lima-ai/prompt.sh, sourced from the end of ~/.bashrc."""
    ws.shell(["bash", "-c", PROMPT_INSTALL_SCRIPT], input=guest_script("lima-ai-prompt.sh"), step="guest tools")


def push_instance_file(ws: Workspace, created_at: str) -> None:
    """Write ~/.config/lima-ai/instance (mode 600) in the guest; lima-ai-info reads it."""
    script = "umask 077 && mkdir -p ~/.config/lima-ai && cat > ~/.config/lima-ai/instance"
    content = render_instance_file(ws.names.project, ws.names.workspace, ws.names.workdir, created_at)
    ws.shell(["bash", "-c", script], input=content, step="guest tools")


def ensure_instance_file(ws: Workspace) -> None:
    """For VMs made before the instance file existed: write one from the host record, or with unknown time."""
    probe = ws.shell(["bash", "-c", "test -f ~/.config/lima-ai/instance"], check=False, step="guest tools")
    if probe.returncode != 0:
        info = lookup(ws.name) or {}
        push_instance_file(ws, info.get("created_at", "unknown"))


def ssh_keys_wanted(ws: Workspace) -> bool:
    """Whether ~/.ssh private keys go into the VM: the config.toml answer, or ask once and save it."""
    setting = ws.cfg.sync.ssh_keys
    if setting is not None:
        return setting
    keys = find_private_keys(ws.host_home)
    if not keys:
        return False
    names = ", ".join(key.name for key in keys)
    answer = click.confirm(f"Copy these SSH private keys into the VM? {names}", default=False, err=True)
    path = save_ssh_keys(answer)
    note(f"Saved ssh_keys = {str(answer).lower()} under [sync] in {path}; edit it to change your mind.")
    return answer


def push_claude_and_git(ws: Workspace, instance: Instance, ssh_keys: bool) -> None:
    note("==> Claude config")
    push_claude_config(ws.runner, instance, ws.guest_home, ws.cfg.developer_dir, ws.host_home)
    note("==> Git config" + (" and SSH keys" if ssh_keys else ""))
    push_git_config(ws.runner, instance, ws.host_home, ssh_keys=ssh_keys)


def _git_position(run, repo: str) -> tuple[str, str] | None:
    """(branch, commit) checked out in repo, or None when it is not a git repository."""
    head = run(["git", "-C", repo, "rev-parse", "HEAD"], check=False, step="sync")
    if head.returncode != 0:
        return None
    branch = run(["git", "-C", repo, "symbolic-ref", "-q", "--short", "HEAD"], check=False, step="sync")
    return (branch.stdout.strip() or "(detached HEAD)", head.stdout.strip())


def sync_project(ws: Workspace, instance: Instance, ask: bool) -> None:
    source = project_dir(ws.cfg.developer_dir, ws.names)
    workdir = ws.workdir
    if ask:
        note(
            "Note: files that exist on both sides are overwritten with the host version; "
            "files created only in the VM are kept."
        )
        warnings = []
        status = ws.shell(["git", "-C", workdir, "status", "--porcelain"], check=False, step="sync")
        if status.returncode == 0 and status.stdout.strip():
            warnings.append(f"The VM's working copy has uncommitted changes:\n{status.stdout.rstrip()}")
        # .git is copied too, so a VM repo that has moved on gets the host's HEAD, refs and index.
        host = _git_position(ws.runner.run, str(source))
        guest = _git_position(ws.shell, workdir)
        if host and guest and host != guest:
            warnings.append(
                f"The VM's repository is on {guest[0]} at {guest[1][:12]}, the host's on {host[0]} at "
                f"{host[1][:12]}. The copy includes .git, so the VM's HEAD, index and branches that "
                "exist on both sides become the host's (its own commits stay in the reflog). "
                "To bring host commits in, use git fetch in the VM instead."
            )
        if warnings:
            note("\n".join(warnings))
            click.confirm("Overwrite them with the host's copy?", abort=True, err=True)
    ws.shell(["mkdir", "-p", workdir], step="sync")
    exclude_file = state_dir() / "rsync-exclude.txt"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    exclude_file.write_text(rsync_excludes(ws.cfg))
    argv = project_argv(
        source,
        ws.name,
        ws.names.workdir,
        instance.ssh_config,
        exclude_file,
        progress_flags(ws.runner),
    )
    ws.runner.run(argv, interactive=True, step="sync")


def switch_branch(ws: Workspace, branch: str) -> None:
    """Switch the guest working copy to branch, creating it when it does not exist yet."""
    git = ["git", "-C", ws.workdir]
    probe = ws.shell([*git, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False, step="branch")
    create = [] if probe.returncode == 0 else ["-c"]
    ws.shell([*git, "switch", *create, branch], step="branch")


# --- commands


def new(
    ws: Workspace,
    branch: str | None = None,
    cpus: int | None = None,
    memory: str | None = None,
    disk: str | None = None,
    after_project=None,
    created_at: str | None = None,
) -> None:
    """Clone dev-base into a workspace VM and fill it. `after_project` runs last (restore).

    `created_at` is when the user started `new` (the CLI takes it before its prompts); it defaults to now.
    """
    created_at = created_at or utc_now()
    cfg, lima = ws.cfg, ws.lima
    token = auth.read_token()
    existing = {instance.name: instance for instance in lima.list()}
    base = existing.get(BASE_INSTANCE)
    if base is None:
        raise LimaAiError("preflight", f"{BASE_INSTANCE} is not built yet; run `lima-ai base` first")
    if base.running:
        raise LimaAiError("preflight", f"{BASE_INSTANCE} is running; stop it first: limactl stop {BASE_INSTANCE}")
    project_dir(cfg.developer_dir, ws.names)
    if ws.name in existing:
        raise LimaAiError(
            "preflight",
            f"{ws.name} already exists; open it with `{ws.hint('shell')}` or remove it with `{ws.hint('destroy')}`",
        )
    for size in (memory, disk):
        if size is not None:
            gib(size)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)
    if ws.runner.run(["ssh-add", "-l"], check=False, step="preflight").returncode != 0:
        note("warning: ssh-agent has no key loaded; git over SSH will not work in the VM (ssh-add)")
    ssh_keys = ssh_keys_wanted(ws)

    note(f"==> Cloning {BASE_INSTANCE} into {ws.name}")
    lima.clone(BASE_INSTANCE, ws.name, cpus=cpus, memory=memory, disk=disk)
    record(ws, created_at)
    try:
        lima.start(ws.name)
        instance = ws.running_instance()
        note("==> Claude token")
        push_token(ws, token)
        push_claude_and_git(ws, instance, ssh_keys)
        note("==> Guest tools")
        push_info_script(ws)
        push_prompt(ws)
        push_instance_file(ws, created_at)
        note("==> Project")
        sync_project(ws, instance, ask=False)
        if branch:
            switch_branch(ws, branch)
        if after_project:
            after_project()
        card = ws.shell(["bash", "-c", "exec ~/.local/bin/lima-ai-info"], step="info").stdout
    except LimaAiError as err:
        raise LimaAiError(
            err.step,
            f"{err.message}\n{ws.name} is kept. Retry with `{ws.hint('sync')}` (project) or "
            f"`{ws.hint('sync-claude')}` (token, Claude and git config), "
            f"or discard it with `{ws.hint('destroy')}`.",
            err.stderr_tail,
        ) from None

    click.echo(card, nl=False)  # as the VM printed it: the host adds nothing to the connection details
    click.echo(f"Open it with: {ws.hint('shell')}")


def sync(ws: Workspace) -> None:
    sync_project(ws, ws.running_instance(), ask=True)


def sync_claude(ws: Workspace) -> None:
    token = auth.read_token()
    instance = ws.running_instance()
    ssh_keys = ssh_keys_wanted(ws)
    note("==> Claude token")
    push_token(ws, token)
    push_claude_and_git(ws, instance, ssh_keys)
    note("==> Guest tools")
    push_info_script(ws)
    push_prompt(ws)
    ensure_instance_file(ws)


def open_shell(ws: Workspace) -> int:
    ws.running_instance()
    result = ws.lima.shell(ws.name, [], workdir=ws.workdir, interactive=True, check=False)
    return result.returncode


def start(ws: Workspace) -> None:
    ws.instance()
    ws.lima.start(ws.name)


def stop(ws: Workspace) -> None:
    ws.instance()
    ws.lima.stop(ws.name)


def unsaved_work(ws: Workspace) -> list[str]:
    """Uncommitted changes and unpushed commits in the guest working copy, as report lines."""
    workdir = ws.workdir
    if ws.shell(["test", "-d", workdir], check=False, step="destroy").returncode != 0:
        return []
    git = ["git", "-C", workdir]
    status = ws.shell([*git, "status", "--porcelain"], check=False, step="destroy")
    if status.returncode != 0:
        reason = (status.stderr or "").strip().splitlines()[-1:] or ["git failed"]
        return [f"Could not check {workdir} for unsaved work: {reason[0]}"]
    lines = []
    if status.stdout.strip():
        lines += ["Uncommitted changes:", *status.stdout.rstrip().splitlines()]
    log = ws.shell([*git, "log", "--oneline", "@{u}.."], check=False, step="destroy")
    if log.returncode != 0:  # no upstream: every commit that is on no remote
        log = ws.shell([*git, "log", "--oneline", "HEAD", "--not", "--remotes"], check=False, step="destroy")
    commits = log.stdout.splitlines() if log.returncode == 0 else []
    if commits:
        lines += ["Commits not pushed:", *commits[:MAX_LISTED_COMMITS]]
        if len(commits) > MAX_LISTED_COMMITS:
            lines.append(f"... and {len(commits) - MAX_LISTED_COMMITS} more")
    return lines


def remove(ws: Workspace, yes: bool, force: bool) -> None:
    instance = ws.instance()
    risks: list[str] = []
    if instance.running:
        risks = unsaved_work(ws)
    else:
        note(f"{ws.name} is stopped, so unsaved work in it cannot be checked.")
    if not (yes or force):
        click.confirm(f"Delete {ws.name}?", abort=True, err=True)
    if risks and not force:
        note("\n".join(risks))
        click.confirm("This work exists only in the VM and will be lost. Delete anyway?", abort=True, err=True)
    ws.lima.delete(ws.name)
    forget(ws.name)
    click.echo(f"Deleted {ws.name}.")


def workspace_vms(lima: Limactl) -> list[tuple[Instance, dict | None]]:
    """Every dev-* VM but the base image, in limactl order, with its instance record (None when it has none)."""
    return [
        (instance, lookup(instance.name))
        for instance in lima.list()
        if instance.name.startswith("dev-") and instance.name != BASE_INSTANCE
    ]


def table_lines(table: list[list[str]]) -> list[str]:
    """Rows rendered as aligned columns, two spaces apart."""
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    return ["  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip() for row in table]


def list_lines(lima: Limactl) -> list[str]:
    """The `list` table (header first); empty when there are no workspace VMs. Asks running VMs for their branch."""
    rows = []
    for instance, info in workspace_vms(lima):
        project = info["project"] if info else "?"
        workspace = info["workspace"] if info else instance.name.removeprefix("dev-")
        branch = "-"
        if instance.running and info:
            workdir = f"{lima.home(instance.name)}/work/{info['slug']}"
            position = _git_position(partial(lima.shell, instance.name), workdir)
            if position:
                branch = position[0]
        rows.append([project, workspace, instance.status, branch, f"lima-{instance.name}.local"])
    if not rows:
        return []
    return table_lines([["PROJECT", "WORKSPACE", "STATUS", "BRANCH", "FQDN"], *rows])


def list_vms(runner: Runner) -> None:
    lines = list_lines(Limactl(runner))
    if not lines:
        click.echo("no workspace VMs; create one with `lima-ai new`")
        return
    for line in lines:
        click.echo(line)
