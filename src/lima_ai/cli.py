import shutil
import sys
from pathlib import Path

import click

from lima_ai import __version__, auth, base, instance
from lima_ai.config import Config, load_config
from lima_ai.errors import LimaAiError
from lima_ai.render import render_template
from lima_ai.runner import Runner

TOOL_HINTS = {
    "limactl": "install Lima: brew install lima",
    "rsync": "rsync ships with macOS; check your PATH",
}


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
    """What every command needs; tests pass their own runner and config."""

    def __init__(
        self,
        verbose: bool = False,
        runner: Runner | None = None,
        config: Config | None = None,
        home: Path | None = None,
    ):
        self.verbose = verbose
        self._runner = runner
        self._config = config
        self.home = home or Path.home()

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
                raise LimaAiError("preflight", f"{tool} not found on PATH ({TOOL_HINTS[tool]})")

    def feature(self, project: str, feat: str) -> instance.Feature:
        self.require("limactl")
        return instance.Feature(self.config, self.runner, self.home, project, feat)


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
    """Build the golden dev-base VM that feature VMs are cloned from."""
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


def feature_command(name: str | None = None, **settings):
    """A command taking PROJECT FEAT, the way most lima-ai commands do."""

    def decorate(func):
        func = click.argument("feat")(func)
        func = click.argument("project")(func)
        return cli.command(name, **settings)(func)

    return decorate


@feature_command()
@click.option("--branch", help="Create and switch to this branch in the VM's working copy.")
@click.option("--cpus", type=int, help="CPUs for this VM (default: dev-base's).")
@click.option("--memory", help="Memory in GiB, e.g. 16GiB (default: dev-base's).")
@click.option("--disk", help="Disk size in GiB, e.g. 100GiB (default: dev-base's).")
@pass_app
def new(app: App, project: str, feat: str, branch, cpus, memory, disk) -> None:
    """Create a feature VM for PROJECT (a folder under developer_dir) and FEAT."""
    app.require("rsync")
    feature = app.feature(project, feat)
    instance.new(feature, branch=branch, cpus=cpus, memory=memory, disk=disk)


@feature_command()
@pass_app
def sync(app: App, project: str, feat: str) -> None:
    """Copy the host project into the VM again (no deletions)."""
    app.require("rsync")
    instance.sync(app.feature(project, feat))


@feature_command("sync-claude")
@pass_app
def sync_claude(app: App, project: str, feat: str) -> None:
    """Push the Claude token, Claude config and git config into the VM again."""
    app.require("rsync")
    instance.sync_claude(app.feature(project, feat))


@feature_command()
@pass_app
def shell(app: App, project: str, feat: str) -> None:
    """Open a shell in the VM's working copy (SSH agent forwarded)."""
    instance.open_shell(app.feature(project, feat))


@feature_command()
@pass_app
def start(app: App, project: str, feat: str) -> None:
    """Start a stopped feature VM."""
    instance.start(app.feature(project, feat))


@feature_command()
@pass_app
def stop(app: App, project: str, feat: str) -> None:
    """Stop a feature VM."""
    instance.stop(app.feature(project, feat))


@feature_command()
@click.option("--yes", is_flag=True, help="Skip the first confirmation.")
@click.option("--force", is_flag=True, help="Skip every confirmation, including the one about unsaved work.")
@pass_app
def rm(app: App, project: str, feat: str, yes: bool, force: bool) -> None:
    """Delete a feature VM, after checking it for uncommitted or unpushed work."""
    instance.remove(app.feature(project, feat), yes=yes, force=force)


@cli.command("ls")
@click.option("--port", type=int, help="Port for the URL column (default: app_port).")
@pass_app
def ls(app: App, port: int | None) -> None:
    """List feature VMs with their mDNS name, IP and app URL."""
    app.require("limactl")
    instance.list_vms(app.runner, port or app.config.app_port)


def main() -> None:
    cli()
