import shutil
import sys

import click

from lima_ai import __version__, auth, base
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

    def __init__(self, verbose: bool = False, runner: Runner | None = None, config: Config | None = None):
        self.verbose = verbose
        self._runner = runner
        self._config = config

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


def main() -> None:
    cli()
