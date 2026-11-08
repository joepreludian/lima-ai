import os
import textwrap

import click

from lima_ai.config import Config, state_dir
from lima_ai.errors import LimaAiError
from lima_ai.hook import Hook
from lima_ai.limactl import Limactl
from lima_ai.naming import BASE_INSTANCE
from lima_ai.render import guest_script, render_base
from lima_ai.runner import Runner

BANNER_WIDTH = 100


def banner(rebuild: bool, hook: Hook | None) -> str:
    """The box printed before a build: the command, which hook, where the logs are."""
    command = "lima-ai base"
    if hook is not None and hook.source == "flag":
        command += f" --use-hook {hook.display}"
    if rebuild:
        command += " --rebuild"
    if hook is None:
        hook_line, note = "hook:  none (lima-ai base --init-hook PATH writes a starter)", ""
    elif hook.source == "flag":
        hook_line, note = f"hook:  {hook.display}", "(from --use-hook, saved to config.toml)"
    else:
        hook_line, note = f"hook:  {hook.display}", "(from config.toml)"
    lima_home = os.environ.get("LIMA_HOME") or "~/.lima"
    # Long values (a hook path outside $HOME) wrap under their label instead of widening the box.
    wrapped = [
        *_wrap(command),
        *_wrap_with_note(hook_line, note),
        *_wrap(f"logs:  output streams below; Lima's own logs are in {lima_home}/{BASE_INSTANCE}/"),
        "       (serialv.log has the provisioning output, ha.stderr.log the host side)",
        f"debug: if a step fails {BASE_INSTANCE} is left running: limactl shell {BASE_INSTANCE}",
    ]
    width = max(len(line) for line in wrapped)
    top = "┌" + "─" * (width + 2) + "┐"
    bottom = "└" + "─" * (width + 2) + "┘"
    return "\n".join([top, *(f"│ {line.ljust(width)} │" for line in wrapped), bottom])


def _wrap(line: str) -> list[str]:
    return textwrap.wrap(line, BANNER_WIDTH - 4, subsequent_indent=" " * 7, break_on_hyphens=False)


def _wrap_with_note(line: str, note: str) -> list[str]:
    """Wrap `line`, then add `note` whole: after the last part when it fits, else on its own indented line."""
    parts = _wrap(line)
    if not note:
        return parts
    if len(parts[-1]) + 2 + len(note) <= BANNER_WIDTH - 4:
        parts[-1] += "  " + note
    else:
        parts.append(" " * 7 + note)
    return parts


def build(cfg: Config, runner: Runner, rebuild: bool, hook: Hook | None = None) -> None:
    """Build, verify and seal the golden dev-base VM that workspaces are cloned from."""
    lima = Limactl(runner)
    template = render_base(cfg, state_dir() / "base")
    existing = lima.get(BASE_INSTANCE)
    if existing and not rebuild:
        message = f"{BASE_INSTANCE} is already built; use --rebuild to replace it"
        if hook is not None and hook.source == "flag":
            message += f" (hook saved: lima-ai base --rebuild will use {hook.display})"
        raise LimaAiError("base", message)
    click.echo(banner(rebuild, hook), err=True)
    if existing:
        click.echo(f"==> Deleting the old {BASE_INSTANCE}", err=True)
        lima.delete(BASE_INSTANCE)
    cfg.backups_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"==> Creating {BASE_INSTANCE} (provisioning takes several minutes)", err=True)
    lima.create_and_start(BASE_INSTANCE, template)

    if hook is not None:
        click.echo(f"==> Running hook {hook.display}", err=True)
        home = lima.home(BASE_INSTANCE)
        result = lima.shell(
            BASE_INSTANCE,
            ["sudo", "bash", "-c", hook.content],
            workdir=home,
            interactive=True,
            check=False,
            step="hook",
        )
        if result.returncode != 0:
            raise LimaAiError(
                "hook",
                f"hook {hook.path} failed (exit {result.returncode}). "
                f"{BASE_INSTANCE} is left running for inspection: limactl shell {BASE_INSTANCE}",
            )

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
    click.echo(f"{BASE_INSTANCE} is ready. Create a workspace VM with: lima-ai new")
