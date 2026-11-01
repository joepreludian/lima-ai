import shutil
import sys
from pathlib import Path

import click

from lima_ai import __version__, auth, backup, base, doctor, instance, wizard
from lima_ai.config import Config, load_config
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
@pass_app
def base_command(app: App, rebuild: bool) -> None:
    """Build the golden dev-base VM that workspace VMs are cloned from."""
    app.require("limactl")
    base.build(app.config, app.runner, rebuild)


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


def workspace_command(name: str | None = None, **settings):
    """A command taking PROJECT WORKSPACE, the way most lima-ai commands do."""

    def decorate(func):
        func = click.argument("workspace")(func)
        func = click.argument("project")(func)
        return cli.command(name, **settings)(func)

    return decorate


@cli.command()
@click.argument("project", required=False)
@click.argument("workspace", required=False)
@click.option("--branch", help="Git branch to create or switch to in the VM (default: the workspace name).")
@click.option("--no-branch", is_flag=True, help="Stay on the branch the host has checked out.")
@click.option(
    "--restore", "restore_from", metavar="BACKUP", help="Restore this backup (under backups_dir) into the VM."
)
@click.option("--cpus", type=int, help="CPUs for this VM (default: dev-base's).")
@click.option("--memory", help="Memory in GiB, e.g. 16GiB (default: dev-base's).")
@click.option("--disk", help="Disk size in GiB, e.g. 100GiB (default: dev-base's).")
@pass_app
def new(app: App, project, workspace, branch, no_branch, restore_from, cpus, memory, disk) -> None:
    """Create a workspace VM for PROJECT (a folder under developer_dir); asks for what is missing."""
    app.require("rsync", "limactl")
    request = wizard.fill(app.config, app.runner, app.interactive, project, workspace, branch, no_branch)
    ws = app.workspace(request.project, request.workspace)
    after_project = backup.restore_step(ws, restore_from) if restore_from else None
    instance.new(ws, branch=request.branch, cpus=cpus, memory=memory, disk=disk, after_project=after_project)
    if app.interactive and click.confirm("Open a shell in it now?", default=True, err=True):
        sys.exit(instance.open_shell(ws))


@workspace_command()
@pass_app
def sync(app: App, project: str, workspace: str) -> None:
    """Copy the host project into the VM again (no deletions)."""
    app.require("rsync")
    instance.sync(app.workspace(project, workspace))


@workspace_command("sync-claude")
@pass_app
def sync_claude(app: App, project: str, workspace: str) -> None:
    """Push the Claude token, Claude config and git config into the VM again."""
    app.require("rsync")
    instance.sync_claude(app.workspace(project, workspace))


@workspace_command()
@pass_app
def shell(app: App, project: str, workspace: str) -> None:
    """Open a shell in the VM's working copy (SSH agent forwarded)."""
    instance.open_shell(app.workspace(project, workspace))


@workspace_command()
@pass_app
def start(app: App, project: str, workspace: str) -> None:
    """Start a stopped workspace VM."""
    instance.start(app.workspace(project, workspace))


@workspace_command()
@pass_app
def stop(app: App, project: str, workspace: str) -> None:
    """Stop a workspace VM."""
    instance.stop(app.workspace(project, workspace))


@workspace_command()
@click.option("--yes", is_flag=True, help="Skip the first confirmation.")
@click.option("--force", is_flag=True, help="Skip every confirmation, including the one about unsaved work.")
@pass_app
def destroy(app: App, project: str, workspace: str, yes: bool, force: bool) -> None:
    """Delete a workspace VM, after checking it for uncommitted or unpushed work."""
    instance.remove(app.workspace(project, workspace), yes=yes, force=force)


@workspace_command("backup")
@click.option("--full", is_flag=True, help="Back up the whole Docker daemon instead of this project.")
@click.option("--no-images", is_flag=True, help="Leave out locally built images.")
@click.option("--no-external", is_flag=True, help="Leave out the project's external volumes.")
@click.option(
    "--compose-file",
    "compose_files",
    multiple=True,
    metavar="FILE",
    help="Compose file, relative to the project root (repeatable, in order); replaces detection.",
)
@pass_app
def backup_command(app: App, project: str, workspace: str, full, no_images, no_external, compose_files) -> None:
    """Back up the project's Docker volumes and built images from the VM to backups_dir."""
    backup.run_backup(app.workspace(project, workspace), full, no_images, no_external, compose_files)


@workspace_command("restore")
@click.argument("backup_path", metavar="BACKUP")
@click.option("--overwrite", is_flag=True, help="Empty and refill volumes that already exist in the VM.")
@click.option("--full", is_flag=True, help="Restore everything in the backup under its recorded names.")
@click.option(
    "--compose-file",
    "compose_files",
    multiple=True,
    metavar="FILE",
    help="Compose file, relative to the project root (repeatable, in order); replaces detection.",
)
@pass_app
def restore_command(app: App, project: str, workspace: str, backup_path, overwrite, full, compose_files) -> None:
    """Restore BACKUP (a path under backups_dir) into the VM."""
    backup.run_restore(app.workspace(project, workspace), backup_path, overwrite, full, compose_files)


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
