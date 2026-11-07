"""The user's base image hook: a script `lima-ai base` runs as root in dev-base after provisioning."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lima_ai.config import Config, config_dir
from lima_ai.errors import LimaAiError
from lima_ai.render import render_hook_starter


def display_path(path: Path) -> str:
    """The path with the home directory shown as `~`."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class Hook:
    path: Path
    source: Literal["flag", "config"]

    @property
    def content(self) -> str:
        return self.path.read_text()

    @property
    def display(self) -> str:
        return display_path(self.path)


def resolve(cfg: Config, use_hook: str | None) -> Hook | None:
    """The hook to build with: --use-hook PATH, else the one saved in config.toml, else none."""
    if use_hook is not None:
        path = Path(use_hook).expanduser().resolve()
        if not path.is_file():
            raise LimaAiError("base", f"hook {path} not found")
        return Hook(path, "flag")
    if cfg.base.hook is not None:
        path = Path(cfg.base.hook)
        if not path.is_file():
            raise LimaAiError(
                "base",
                f"hook {path} not found (saved in {display_path(config_dir() / 'config.toml')}); "
                "pass --use-hook PATH or remove it with lima-ai config --edit",
            )
        return Hook(path, "config")
    return None


def write_starter(path: Path) -> Path:
    """Write the commented starter hook to path; refuse to overwrite."""
    if path.exists():
        raise LimaAiError("base", f"{path} exists; pick another name or delete it first")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_hook_starter())
    path.chmod(0o644)
    return path
