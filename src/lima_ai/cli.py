import shutil
import sys
from dataclasses import dataclass, field

import click

from lima_ai import __version__, base
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


@dataclass
class App:
    verbose: bool
    _config: Config | None = field(default=None, repr=False)

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = load_config()
        return self._config

    @property
    def runner(self) -> Runner:
        return Runner(verbose=self.verbose)

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


def main() -> None:
    cli()
