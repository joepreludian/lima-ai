import json
import re
from pathlib import Path

import click

from lima_ai import auth
from lima_ai.claude_config import push_claude_config
from lima_ai.config import Config, state_dir
from lima_ai.errors import LimaAiError
from lima_ai.gitconfig import push_git_config
from lima_ai.limactl import Instance, Limactl, gib
from lima_ai.naming import BASE_INSTANCE, project_dir, resolve
from lima_ai.render import render_env, rsync_excludes
from lima_ai.runner import Runner
from lima_ai.sync import progress_flags, project_argv

MAX_LISTED_COMMITS = 20


def note(message: str) -> None:
    click.echo(message, err=True)


class Feature:
    """One feature VM: its names, and the guest paths lima-ai works with."""

    def __init__(self, cfg: Config, runner: Runner, host_home: Path, project: str, feat: str) -> None:
        self.cfg = cfg
        self.runner = runner
        self.host_home = host_home
        self.names = resolve(cfg.developer_dir, project, feat)
        self.lima = Limactl(runner)
        self._guest_home: str | None = None

    @property
    def name(self) -> str:
        return self.names.instance

    def hint(self, command: str) -> str:
        return f"lima-ai {command} {self.names.project} {self.names.feat}"

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


# --- instance records (for `ls`: instance names cannot be split back into slug and feat)


def _record_path(name: str) -> Path:
    return state_dir() / "instances" / f"{name}.json"


def record(feature: Feature) -> None:
    path = _record_path(feature.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = feature.names
    path.write_text(json.dumps({"project": names.project, "slug": names.slug, "feat": names.feat}) + "\n")


def lookup(name: str) -> dict | None:
    path = _record_path(name)
    return json.loads(path.read_text()) if path.is_file() else None


def forget(name: str) -> None:
    _record_path(name).unlink(missing_ok=True)


# --- steps shared by new, sync and sync-claude


def push_token(feature: Feature, token: str) -> None:
    """The token goes over stdin into a mode-600 file; it never appears in argv."""
    script = "umask 077 && mkdir -p ~/.config/lima-ai && cat > ~/.config/lima-ai/env && chmod 600 ~/.config/lima-ai/env"
    feature.shell(["bash", "-c", script], input=render_env(token), step="token")


def push_claude_and_git(feature: Feature, instance: Instance) -> None:
    note("==> Claude config")
    push_claude_config(feature.runner, instance, feature.guest_home, feature.cfg.developer_dir, feature.host_home)
    note("==> Git config")
    push_git_config(feature.runner, instance, feature.host_home)


def sync_project(feature: Feature, instance: Instance, ask: bool) -> None:
    source = project_dir(feature.cfg.developer_dir, feature.names)
    workdir = feature.workdir
    if ask:
        note(
            "Note: files that exist on both sides are overwritten with the host version; "
            "files created only in the VM are kept."
        )
        status = feature.shell(["git", "-C", workdir, "status", "--porcelain"], check=False, step="sync")
        if status.returncode == 0 and status.stdout.strip():
            note(f"The VM's working copy has uncommitted changes:\n{status.stdout.rstrip()}")
            click.confirm("Overwrite files that also exist on the host?", abort=True, err=True)
    feature.shell(["mkdir", "-p", workdir], step="sync")
    exclude_file = state_dir() / "rsync-exclude.txt"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    exclude_file.write_text(rsync_excludes(feature.cfg))
    argv = project_argv(
        source,
        feature.name,
        feature.names.workdir,
        instance.ssh_config,
        exclude_file,
        progress_flags(feature.runner),
    )
    feature.runner.run(argv, interactive=True, step="sync")


def guest_ip(lima: Limactl, name: str) -> str | None:
    result = lima.shell(name, ["ip", "-4", "-o", "addr", "show", "lima0"], check=False, step="ip")
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", result.stdout or "")
    return match[1] if match else None


# --- commands


def new(
    feature: Feature,
    branch: str | None = None,
    cpus: int | None = None,
    memory: str | None = None,
    disk: str | None = None,
    after_project=None,
) -> None:
    """Clone dev-base into a feature VM and fill it. `after_project` runs last (restore)."""
    cfg, lima = feature.cfg, feature.lima
    token = auth.read_token()
    existing = {instance.name: instance for instance in lima.list()}
    base = existing.get(BASE_INSTANCE)
    if base is None:
        raise LimaAiError("preflight", f"{BASE_INSTANCE} is not built yet; run `lima-ai base` first")
    if base.running:
        raise LimaAiError("preflight", f"{BASE_INSTANCE} is running; stop it first: limactl stop {BASE_INSTANCE}")
    project_dir(cfg.developer_dir, feature.names)
    if feature.name in existing:
        raise LimaAiError(
            "preflight",
            f"{feature.name} already exists; open it with `{feature.hint('shell')}` "
            f"or remove it with `{feature.hint('rm')}`",
        )
    for size in (memory, disk):
        if size is not None:
            gib(size)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)
    if feature.runner.run(["ssh-add", "-l"], check=False, step="preflight").returncode != 0:
        note("warning: ssh-agent has no key loaded; git over SSH will not work in the VM (ssh-add)")

    note(f"==> Cloning {BASE_INSTANCE} into {feature.name}")
    lima.clone(BASE_INSTANCE, feature.name, cpus=cpus, memory=memory, disk=disk)
    record(feature)
    try:
        lima.start(feature.name)
        instance = feature.running_instance()
        note("==> Claude token")
        push_token(feature, token)
        push_claude_and_git(feature, instance)
        note("==> Project")
        sync_project(feature, instance, ask=False)
        if branch:
            feature.shell(["git", "-C", feature.workdir, "switch", "-c", branch], step="branch")
        if after_project:
            after_project()
    except LimaAiError as err:
        raise LimaAiError(
            err.step,
            f"{err.message}\n{feature.name} is kept. Retry with `{feature.hint('sync')}` (project) or "
            f"`{feature.hint('sync-claude')}` (token, Claude and git config), "
            f"or discard it with `{feature.hint('rm')}`.",
            err.stderr_tail,
        ) from None

    names = feature.names
    click.echo(f"\n{feature.name} is ready.")
    click.echo(f"  mDNS   {names.mdns}")
    click.echo(f"  IP     {guest_ip(lima, feature.name) or 'unknown'}")
    click.echo(f"  URL    {names.url(cfg.app_port)}")
    click.echo(f"  Shell  {feature.hint('shell')}")


def sync(feature: Feature) -> None:
    sync_project(feature, feature.running_instance(), ask=True)


def sync_claude(feature: Feature) -> None:
    token = auth.read_token()
    instance = feature.running_instance()
    note("==> Claude token")
    push_token(feature, token)
    push_claude_and_git(feature, instance)


def open_shell(feature: Feature) -> None:
    feature.running_instance()
    feature.lima.shell(feature.name, [], workdir=feature.workdir, interactive=True, check=False)


def start(feature: Feature) -> None:
    feature.instance()
    feature.lima.start(feature.name)


def stop(feature: Feature) -> None:
    feature.instance()
    feature.lima.stop(feature.name)


def unsaved_work(feature: Feature) -> list[str]:
    """Uncommitted changes and unpushed commits in the guest working copy, as report lines."""
    workdir = feature.workdir
    if feature.shell(["test", "-d", workdir], check=False, step="rm").returncode != 0:
        return []
    git = ["git", "-C", workdir]
    status = feature.shell([*git, "status", "--porcelain"], check=False, step="rm")
    if status.returncode != 0:
        reason = (status.stderr or "").strip().splitlines()[-1:] or ["git failed"]
        return [f"Could not check {workdir} for unsaved work: {reason[0]}"]
    lines = []
    if status.stdout.strip():
        lines += ["Uncommitted changes:", *status.stdout.rstrip().splitlines()]
    log = feature.shell([*git, "log", "--oneline", "@{u}.."], check=False, step="rm")
    if log.returncode != 0:  # no upstream: every commit that is on no remote
        log = feature.shell([*git, "log", "--oneline", "HEAD", "--not", "--remotes"], check=False, step="rm")
    commits = log.stdout.splitlines() if log.returncode == 0 else []
    if commits:
        lines += ["Commits not pushed:", *commits[:MAX_LISTED_COMMITS]]
        if len(commits) > MAX_LISTED_COMMITS:
            lines.append(f"... and {len(commits) - MAX_LISTED_COMMITS} more")
    return lines


def remove(feature: Feature, yes: bool, force: bool) -> None:
    instance = feature.instance()
    risks: list[str] = []
    if instance.running:
        risks = unsaved_work(feature)
    else:
        note(f"{feature.name} is stopped, so unsaved work in it cannot be checked.")
    if not (yes or force):
        click.confirm(f"Delete {feature.name}?", abort=True, err=True)
    if risks and not force:
        note("\n".join(risks))
        click.confirm("This work exists only in the VM and will be lost. Delete anyway?", abort=True, err=True)
    feature.lima.delete(feature.name)
    forget(feature.name)
    click.echo(f"Deleted {feature.name}.")


def list_vms(runner: Runner, port: int) -> None:
    lima = Limactl(runner)
    rows = []
    for instance in lima.list():
        if not instance.name.startswith("dev-") or instance.name == BASE_INSTANCE:
            continue
        info = lookup(instance.name) or {"slug": "?", "feat": instance.name.removeprefix("dev-")}
        mdns = f"lima-{instance.name}.local"
        ip = guest_ip(lima, instance.name) if instance.running else None
        url = f"http://{mdns}:{port}" if instance.running else "-"
        rows.append([info["slug"], info["feat"], instance.status, mdns, ip or "-", url])
    if not rows:
        click.echo("no feature VMs; create one with `lima-ai new <project> <feat>`")
        return
    table = [["PROJECT", "FEAT", "STATUS", "MDNS", "IP", "URL"], *rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    for row in table:
        click.echo("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip())
