import shlex
import shutil
from importlib import resources
from pathlib import Path

import jinja2

from lima_ai import __version__
from lima_ai.config import Config

# Provision scripts in the order Lima runs them, with their mode.
PROVISION = (
    ("10-system.sh", "system"),
    ("20-docker.sh", "system"),
    ("30-node.sh", "user"),
    ("40-rust.sh", "user"),
    ("50-claude.sh", "user"),
    ("60-rtk.sh", "user"),
    ("70-docker-backup.sh", "system"),
)

_env = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)
_env.filters["shquote"] = shlex.quote


def _resource(relative: str):
    return resources.files("lima_ai").joinpath("resources", *relative.split("/"))


def _render(relative: str, context: dict) -> str:
    template = _resource(relative + ".j2")
    if template.is_file():
        return _env.from_string(template.read_text()).render(**context)
    return _resource(relative).read_text()


def _context(cfg: Config) -> dict:
    return {
        "version": __version__,
        "vm": cfg.vm,
        "developer_dir": str(cfg.developer_dir),
        "backups_dir": str(cfg.backups_dir),
        "provision": PROVISION,
        "node_major": cfg.versions.node_major,
        "rtk": cfg.versions.rtk,
        "rtk_sha256": cfg.versions.rtk_sha256,
        "docker_backup": cfg.versions.docker_backup,
        "docker_backup_sha256": cfg.versions.docker_backup_sha256,
    }


def render_template(cfg: Config) -> str:
    """The dev-base Lima template, as `lima-ai template` prints it."""
    return _render("dev-base.yaml", _context(cfg))


def render_base(cfg: Config, dest: Path) -> Path:
    """Write the template and its provision scripts to dest; return the template path."""
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "provision").mkdir(parents=True)
    context = _context(cfg)
    for name, _mode in PROVISION:
        (dest / "provision" / name).write_text(_render(f"provision/{name}", context))
    template = dest / "dev-base.yaml"
    template.write_text(render_template(cfg))
    return template


def guest_script(name: str) -> str:
    return _resource(f"guest/{name}").read_text()


def render_env(token: str) -> str:
    """Content of the guest's ~/.config/lima-ai/env. Never written on the host."""
    return _render("guest/lima-ai.env", {"token": token})


def rsync_excludes(cfg: Config) -> str:
    lines = _resource("rsync-exclude.txt").read_text().splitlines()
    return "\n".join([*lines, *cfg.sync.extra_excludes]) + "\n"
