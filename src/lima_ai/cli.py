import functools
import shutil
import sys
from pathlib import Path

import click

from lima_ai import __version__, auth, base, config_file, doctor, hook, instance, menu, wizard
from lima_ai.aws_config import find_aws_files
from lima_ai.claude_config import offered_hooks, read_settings
from lima_ai.config import Config, config_dir, load_config, save_hooks, save_setting
from lima_ai.errors import LimaAiError
from lima_ai.render import render_template
from lima_ai.runner import Runner


class LimaAiGroup(click.Group):
    """Turns LimaAiError into `error [<step>]: <message>` and exit status 1."""

    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except LimaAiError as err:
            click.echo(f"error [{err.step}]: {err.message}", err=True)
            if err.stderr_tail:
                click.echo(err.stderr_tail, err=True)
            sys.exit(1)


class App:
    """What every command needs; tests pass their own runner, config and interactivity."""

    def __init__(
        self,
        verbose: bool = False,
        runner: Runner | None = None,
        config: Config | None = None,
        home: Path | None = None,
        interactive: bool | None = None,
    ):
        self.verbose = verbose
        self._runner = runner
        self._config = config
        self.home = home or Path.home()
        self._interactive = interactive

    @property
    def interactive(self) -> bool:
        """Whether prompts may run: stdin is a terminal, unless a test says otherwise."""
        if self._interactive is None:
            self._interactive = sys.stdin.isatty()
        return self._interactive

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = load_config()
        return self._config

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(verbose=self.verbose)
        return self._runner

    def require(self, *tools: str) -> None:
        for tool in tools:
            if shutil.which(tool) is None:
                raise LimaAiError("preflight", f"{tool} not found on PATH ({doctor.TOOL_HINTS[tool]})")

    def workspace(self, project: str, workspace: str) -> instance.Workspace:
        self.require("limactl")
        return instance.Workspace(self.config, self.runner, self.home, project, workspace)


pass_app = click.make_pass_decorator(App)


def aws_wanted(app: App, flag: bool | None) -> bool:
    """Whether ~/.aws goes into the VM: the --aws/--no-aws flag, else ask (default yes), else yes."""
    if flag is False:
        return False
    if not find_aws_files(app.home):
        click.echo("~/.aws has nothing to copy; skipping AWS config", err=True)
        return False
    if flag is True or not app.interactive:
        return True
    return click.confirm("Copy your AWS config and SSO session (~/.aws) into the VM?", default=True, err=True)


AWS_OPTION = click.option(
    "--aws/--no-aws", default=None, help="Copy ~/.aws into the VM, or not, without asking (default: ask)."
)


def hooks_wanted(app: App, flag: bool | None) -> tuple[str, ...]:
    """The host hook commands whose scripts go into the VM.

    --no-hooks: none. Otherwise the answer saved in config.toml, asking first (in a terminal) when
    there is none yet, when the host has a hook the answer has never seen, or when --hooks says so.
    """
    if flag is False:
        return ()
    choices = offered_hooks(read_settings(app.home / ".claude"), str(app.home), str(app.config.developer_dir))
    offered = [choice.command for choice in choices]
    if not offered:
        return ()
    saved, skipped = app.config.sync.hooks, app.config.sync.hooks_skipped
    unseen = [command for command in offered if command not in (saved or ()) and command not in skipped]
    if not app.interactive or not (flag is True or saved is None or unseen):
        return tuple(command for command in offered if command in (saved or ()))
    ticked = menu.choose_hooks(choices, saved or (), str(app.home))
    if ticked is None:
        raise click.Abort()
    # Commands the host no longer has stay in the file: they may come back.
    keep = [*ticked, *(command for command in saved or () if command not in offered)]
    skip = [
        *(command for command in offered if command not in ticked),
        *(command for command in skipped if command not in offered),
    ]
    path = save_hooks(keep, skip)
    click.echo(f"Saved hooks under [sync] in {path}; run with --hooks to choose again.", err=True)
    return tuple(ticked)


HOOKS_OPTION = click.option(
    "--hooks/--no-hooks",
    default=None,
    help="Choose again which host hooks go into the VM, or copy none this time, without asking "
    "(default: ask once and remember).",
)


@click.group(cls=LimaAiGroup)
@click.version_option(__version__, prog_name="lima-ai")
@click.option("-v", "--verbose", is_flag=True, help="Echo every command lima-ai runs.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Disposable Lima VMs for running Claude Code agents in parallel."""
    if ctx.obj is None:
        ctx.obj = App(verbose=verbose)


@cli.command()
@pass_app
def template(app: App) -> None:
    """Print the rendered dev-base Lima template."""
    click.echo(render_template(app.config), nl=False)


@cli.command("base")
@click.option("--rebuild", is_flag=True, help="Delete and rebuild an existing dev-base.")
@click.option(
    "--use-hook",
    "use_hook",
    metavar="PATH",
    help="Run this script in dev-base after provisioning, and remember it in config.toml.",
)
@click.option(
    "--init-hook", "init_hook", metavar="PATH", help="Write a commented starter hook script to PATH and exit."
)
@pass_app
def base_command(app: App, rebuild: bool, use_hook: str | None, init_hook: str | None) -> None:
    """Build the golden dev-base VM that workspace VMs are cloned from."""
    if init_hook is not None:
        if use_hook is not None or rebuild:
            raise click.UsageError("--init-hook cannot be combined with --use-hook or --rebuild")
        path = hook.write_starter(Path(init_hook).expanduser().resolve())
        click.echo(f"Wrote {path}. Edit it, then build with:\n  lima-ai base --use-hook {path} --rebuild")
        return
    app.require("limactl")
    selected = hook.resolve(app.config, use_hook)
    if use_hook is not None and selected is not None:
        save_setting("base", "hook", str(selected.path))
    base.build(app.config, app.runner, rebuild, hook=selected)


@cli.command("config")
@click.option("--edit", is_flag=True, help="Open config.toml in $VISUAL/$EDITOR, creating a commented one first.")
@pass_app
def config_command(app: App, edit: bool) -> None:
    """Print the settings in effect as TOML, or edit the config file."""
    path = config_dir() / "config.toml"
    if edit:
        config_file.edit(path)
        return
    click.echo(config_file.effective_toml(app.config, path), nl=False)


@cli.command("auth")
@click.option("--from-stdin", is_flag=True, help="Read the token from stdin instead of running claude.")
@pass_app
def auth_command(app: App, from_stdin: bool) -> None:
    """Create a long-lived Claude token for the VMs and store it (mode 600)."""
    if from_stdin:
        token = sys.stdin.read()
    else:
        auth.run_setup_token(app.runner)
        token = click.prompt("Paste the token printed above", hide_input=True)
    auth.write_token(token)
    click.echo(f"Token saved to {auth.token_path()}")


def resolve_vm(app: App, command: str, project: str | None, workspace: str | None, running: bool = True):
    """PROJECT WORKSPACE as given, or with neither the VM picked among the running (or not running) ones."""
    if (project is None) != (workspace is None):
        state = "running" if running else "stopped"
        raise click.UsageError(f"give both PROJECT and WORKSPACE, or neither to pick from the {state} VMs")
    if project is None or workspace is None:
        app.require("limactl")
        return instance.pick_vm(app.runner, app.interactive, command, running)
    return project, workspace


def workspace_command(name: str | None = None, running: bool = True, **settings):
    """A command taking PROJECT WORKSPACE, the way most lima-ai commands do.

    With neither argument the VM is picked from a menu of the running ones (running=False: the stopped ones).
    """

    def decorate(func):
        command = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, project: str | None, workspace: str | None, **kwargs):
            app = click.get_current_context().find_object(App)
            project, workspace = resolve_vm(app, command, project, workspace, running)
            return func(*args, project=project, workspace=workspace, **kwargs)

        wrapper = click.argument("workspace", required=False)(wrapper)
        wrapper = click.argument("project", required=False)(wrapper)
        return cli.command(name, **settings)(wrapper)

    return decorate


@cli.command()
@click.argument("project", required=False)
@click.argument("workspace", required=False)
@click.option("--branch", help="Git branch to create or switch to in the VM (default: the workspace name).")
@click.option("--no-branch", is_flag=True, help="Stay on the branch the host has checked out.")
@click.option("--cpus", type=int, help="CPUs for this VM (default: dev-base's).")
@click.option("--memory", help="Memory in GiB, e.g. 16GiB (default: dev-base's).")
@click.option("--disk", help="Disk size in GiB, e.g. 100GiB (default: dev-base's).")
@AWS_OPTION
@HOOKS_OPTION
@pass_app
def new(app: App, project, workspace, branch, no_branch, cpus, memory, disk, aws, hooks) -> None:
    """Create a workspace VM for PROJECT (a folder under developer_dir); asks for what is missing."""
    app.require("rsync", "limactl")
    created_at = instance.utc_now()  # when the user started, not when they finished answering the prompts
    request = wizard.fill(app.config, app.runner, app.interactive, project, workspace, branch, no_branch)
    aws = aws_wanted(app, aws)  # asked here so every prompt precedes the clone
    hooks = hooks_wanted(app, hooks)
    ws = app.workspace(request.project, request.workspace)
    instance.new(
        ws,
        branch=request.branch,
        cpus=cpus,
        memory=memory,
        disk=disk,
        created_at=created_at,
        aws=aws,
        hooks=hooks,
    )
    if app.interactive and click.confirm("Open a shell in it now?", default=True, err=True):
        sys.exit(instance.open_shell(ws))


@workspace_command()
@pass_app
def sync(app: App, project: str, workspace: str) -> None:
    """Copy the host project into the VM again (no deletions); with no arguments, pick the VM from a menu."""
    app.require("rsync")
    instance.sync(app.workspace(project, workspace))


@workspace_command("sync-claude")
@AWS_OPTION
@HOOKS_OPTION
@pass_app
def sync_claude(app: App, project: str, workspace: str, aws: bool | None, hooks: bool | None) -> None:
    """Push the Claude token, Claude config, git config and (if confirmed) AWS config into the VM again.

    With no arguments, pick the VM from a menu."""
    app.require("rsync")
    aws = aws_wanted(app, aws)
    instance.sync_claude(app.workspace(project, workspace), aws=aws, hooks=hooks_wanted(app, hooks))


@cli.command()
@click.argument("project", required=False)
@click.argument("workspace", required=False)
@pass_app
def shell(app: App, project: str | None, workspace: str | None) -> None:
    """Open a shell in a VM's working copy (SSH agent forwarded); with no arguments, the only running VM or a menu."""
    project, workspace = resolve_vm(app, "shell", project, workspace)
    instance.open_shell(app.workspace(project, workspace))


@workspace_command(running=False)
@pass_app
def start(app: App, project: str, workspace: str) -> None:
    """Start a stopped workspace VM; with no arguments, pick it from a menu."""
    instance.start(app.workspace(project, workspace))


@workspace_command()
@pass_app
def stop(app: App, project: str, workspace: str) -> None:
    """Stop a workspace VM; with no arguments, pick it from a menu."""
    instance.stop(app.workspace(project, workspace))


@cli.command()
@click.argument("project", required=False)
@click.argument("workspace", required=False)
@click.option("--yes", is_flag=True, help="Skip the first confirmation.")
@click.option("--force", is_flag=True, help="Skip every confirmation, including the one about unsaved work.")
@pass_app
def destroy(app: App, project: str | None, workspace: str | None, yes: bool, force: bool) -> None:
    """Delete workspace VMs after checking them for unsaved work; with no arguments, tick them in a checklist."""
    if (project is None) != (workspace is None):
        raise click.UsageError("give both PROJECT and WORKSPACE, or neither to pick from a list")
    if project is not None and workspace is not None:
        instance.remove(app.workspace(project, workspace), yes=yes, force=force)
        return
    app.require("limactl")
    picks = instance.pick_vms(app.runner, app.interactive)
    if picks:
        instance.remove_many([app.workspace(p, w) for p, w in picks], yes=yes, force=force)


@cli.command("list")
@pass_app
def list_command(app: App) -> None:
    """List workspace VMs with their project, status, branch and FQDN."""
    app.require("limactl")
    instance.list_vms(app.runner)


cli.add_command(list_command, "ls")


@cli.command("doctor")
@pass_app
def doctor_command(app: App) -> None:
    """Check that this machine has everything lima-ai needs."""
    checks = doctor.run_checks(app.runner)
    click.echo(doctor.render(checks), nl=False)
    if any(check.status == "fail" for check in checks):
        sys.exit(1)


def main() -> None:
    cli()
