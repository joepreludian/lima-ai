"""Printing and editing ~/.config/lima-ai/config.toml, for `lima-ai config [--edit]`."""

import json
from pathlib import Path

import click

from lima_ai.config import Config, load_config
from lima_ai.errors import LimaAiError
from lima_ai.hook import display_path

DOCS_URL = "https://lima-ai.readthedocs.io/configuration/"

# (section, key, comment) in the order the manual lists them; None is the top level.
SETTINGS: tuple[tuple[str | None, str, str], ...] = (
    (None, "developer_dir", "where <project> paths start"),
    (None, "backups_dir", "mounted read-write at /backups in every VM"),
    ("vm", "cpus", "dev-base defaults; new --cpus/--memory/--disk override per VM"),
    ("vm", "memory", ""),
    ("vm", "disk", ""),
    ("vm", "ubuntu_release", ""),
    ("versions", "node_major", "pinned tools installed into dev-base"),
    ("versions", "rtk", ""),
    ("versions", "rtk_sha256", ""),
    ("versions", "docker_backup", ""),
    ("versions", "docker_backup_sha256", ""),
    ("versions", "aws_cli", ""),
    ("versions", "aws_cli_sha256", ""),
    ("versions", "ssm_plugin", ""),
    ("versions", "ssm_plugin_sha256", ""),
    ("sync", "extra_excludes", "added to the project rsync excludes"),
    ("sync", "ssh_keys", "copy ~/.ssh private keys into VMs; unset = ask once and save the answer"),
    ("base", "hook", "a script lima-ai base runs as root in dev-base after its own provisioning"),
)

# What an unset optional key means, for `lima-ai config`, and an example value for the template.
UNSET_NOTE = {
    "ssh_keys": "asked once and saved",
    "hook": "lima-ai base --use-hook PATH sets it",
}
EXAMPLE = {"ssh_keys": False, "hook": "~/lima/custom.sh"}


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Path):
        return json.dumps(display_path(value))
    if isinstance(value, tuple):
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(value)


def _lines(cfg: Config | None) -> list[str]:
    """Settings as TOML lines: cfg's values, or (cfg None) every key commented at its default."""
    defaults = Config()
    lines: list[str] = []
    current: str | None = None
    for section, key, comment in SETTINGS:
        if section != current:
            lines.append("")
            lines.append(f"[{section}]")
            current = section
        owner = cfg if cfg is not None else defaults
        value = getattr(getattr(owner, section) if section else owner, key)
        suffix = f"  # {comment}" if comment else ""
        if cfg is None:
            if value is None:
                value = EXAMPLE[key]
            lines.append(f"# {key} = {_toml_value(value)}{suffix}")
        elif value is None:
            lines.append(f"# {key} is unset: {UNSET_NOTE[key]}")
        else:
            lines.append(f"{key} = {_toml_value(value)}{suffix}")
    return lines


def effective_toml(cfg: Config, path: Path) -> str:
    """The settings in effect, as TOML, headed by a comment naming the file."""
    header = f"# {display_path(path)}" + ("" if path.exists() else " (not found; showing defaults)")
    return "\n".join([header, *_lines(cfg)]) + "\n"


def template_toml() -> str:
    """A config file with live table headers and every key commented at its default."""
    header = f"# lima-ai settings. Uncomment a line to change it; see {DOCS_URL}"
    return "\n".join([header, *_lines(None)]) + "\n"


def edit(path: Path) -> None:
    """Open path in $VISUAL/$EDITOR, creating it from the template first; then check it loads."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template_toml())
    try:
        click.edit(filename=str(path))
    except click.ClickException as exc:
        raise LimaAiError("config", f"editor failed ({exc.message}); check $VISUAL or $EDITOR") from None
    load_config(path)
