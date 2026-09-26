import click

from lima_ai.config import Config, state_dir
from lima_ai.errors import LimaAiError
from lima_ai.limactl import Limactl
from lima_ai.naming import BASE_INSTANCE
from lima_ai.render import guest_script, render_base
from lima_ai.runner import Runner


def build(cfg: Config, runner: Runner, rebuild: bool) -> None:
    """Build, verify and seal the golden dev-base VM that features are cloned from."""
    lima = Limactl(runner)
    template = render_base(cfg, state_dir() / "base")
    if lima.get(BASE_INSTANCE):
        if not rebuild:
            raise LimaAiError("base", f"{BASE_INSTANCE} is already built; use --rebuild to replace it")
        click.echo(f"==> Deleting the old {BASE_INSTANCE}", err=True)
        lima.delete(BASE_INSTANCE)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"==> Creating {BASE_INSTANCE} (provisioning takes several minutes)", err=True)
    lima.create_and_start(BASE_INSTANCE, template)

    click.echo("==> Verifying the toolchain", err=True)
    try:
        lima.shell(BASE_INSTANCE, ["bash", "-c", guest_script("verify-base.sh")], step="verify-base")
    except LimaAiError as err:
        raise LimaAiError(
            "verify-base",
            f"{err.message}. {BASE_INSTANCE} is left running for inspection: limactl shell {BASE_INSTANCE}",
            err.stderr_tail,
        ) from None

    click.echo("==> Sealing and stopping", err=True)
    lima.shell(BASE_INSTANCE, ["sudo", "bash", "-c", guest_script("seal-base.sh")], step="seal-base")
    lima.stop(BASE_INSTANCE)
    click.echo(f"{BASE_INSTANCE} is ready. Create a feature VM with: lima-ai new <project> <feat>")
