import json
import os
import re
import shlex
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import click

from lima_ai.config import Config
from lima_ai.errors import LimaAiError
from lima_ai.instance import Feature, note

GUEST_BACKUPS = "/backups/docker"

# The files plain `docker compose` loads from a project root, in precedence
# order (observed with Docker Compose 5.5.1).
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
OVERRIDE_NAMES = (
    "compose.override.yml",
    "compose.override.yaml",
    "docker-compose.override.yml",
    "docker-compose.override.yaml",
)


def parse_dotenv(text: str) -> dict[str, str]:
    """KEY=VALUE lines the way compose reads .env: export prefix, quotes, ` #` comments."""
    env = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value.find(value[0], 1) != -1:
            value = value[1 : value.find(value[0], 1)]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        env[key.strip()] = value
    return env


def detect_compose_files(names: set[str], dotenv: str | None) -> list[str]:
    """Compose files, relative to the project root, that `docker compose` would load there."""
    env = parse_dotenv(dotenv) if dotenv else {}
    if env.get("COMPOSE_FILE"):
        separator = env.get("COMPOSE_PATH_SEPARATOR") or ":"
        return [name for name in env["COMPOSE_FILE"].split(separator) if name]
    main = next((name for name in COMPOSE_NAMES if name in names), None)
    if main is None:
        return []
    override = next((name for name in OVERRIDE_NAMES if name in names), None)
    return [main, override] if override else [main]


def compose_files(
    explicit: Sequence[str], names: set[str], dotenv: str | None, required: bool, where: str
) -> list[str]:
    """--compose-file values if given, else detection; an error when required and none is found."""
    files = list(explicit) or detect_compose_files(names, dotenv)
    if required and not files:
        raise LimaAiError(
            "compose files",
            f"no compose file found in {where}; pass --compose-file FILE, or use --full "
            "to back up the whole Docker daemon",
        )
    return files


def backup_name(slug: str, feat: str, full: bool, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{slug}-{feat}-full-{stamp}" if full else f"{slug}-{feat}-{stamp}"


def backup_argv(files: list[str], dest: str, full: bool, no_images: bool, no_external: bool) -> list[str]:
    argv = ["docker-backup", "backup"]
    if not full:
        argv += ["--from-docker-compose", ",".join(files)]
    if no_images:
        argv.append("--no-images")
    if no_external and not full:
        argv.append("--no-external")
    return [*argv, dest]


def restore_argv(files: list[str], source: str, overwrite: bool) -> list[str]:
    """Never --yes: docker-backup's preview and prompt are the confirmation."""
    argv = ["docker-backup", "restore"]
    if files:
        argv += ["--from-docker-compose", ",".join(files)]
    argv.append(source)
    return [*argv, "--overwrite"] if overwrite else argv


def compose_argv(files: list[str], *command: str) -> list[str]:
    return ["docker", "compose", *[arg for name in files for arg in ("-f", name)], *command]


def _display(path: Path) -> str:
    """A host path for copy-pasting: ~-relative when under the home folder, shell-quoted."""
    try:
        return "~/" + shlex.quote(path.relative_to(Path.home()).as_posix())
    except ValueError:
        return shlex.quote(str(path))


def host_commands(
    cfg: Config, project: str, files: list[str], explicit: bool, name: str, full: bool, no_external: bool
) -> list[str]:
    """Commands (printed, never run) that restore a backup into the host's Colima."""
    source = _display(cfg.backups_dir / name)
    compose = shlex.join(compose_argv(files)) if explicit else "docker compose"
    if full:
        restore = f"docker-backup restore {source}"
        overwrite_comment = "replaces every volume in the backup that exists on the host"
    else:
        restore = f"docker-backup restore --from-docker-compose {shlex.quote(','.join(files))} {source}"
        overwrite_comment = "replaces this project's existing volumes"
    lines = [
        f"cd {_display(cfg.developer_dir / project)}",
        f"{compose} stop",
        f"docker-backup info {source}",
        f"{restore}              # new volumes only",
        f"{restore} --overwrite  # {overwrite_comment}",
        f"{compose} up -d",
    ]
    if full:
        lines.append(
            "# Note: with a full backup, --overwrite replaces every volume in its manifest that "
            "already exists on the host, whatever project it belongs to."
        )
    elif not no_external:
        lines.append(
            "# Note: --overwrite also replaces the project's external volumes, which on the host "
            "may be shared with other projects; back up with --no-external to leave them out."
        )
    return lines


def resolve_backup(cfg: Config, arg: str) -> tuple[Path, str]:
    """A backup given as a host path or relative to backups_dir → (host path, guest path)."""
    path = Path(arg).expanduser()
    if not path.is_absolute():
        path = cfg.backups_dir / path
    path = Path(os.path.normpath(path))
    try:
        relative = path.relative_to(os.path.normpath(cfg.backups_dir))
    except ValueError:
        raise LimaAiError("restore", f"the backup must be inside {cfg.backups_dir} (got {arg})") from None
    if relative == Path("."):
        raise LimaAiError("restore", f"{arg} is the backups folder itself; name a backup inside it")
    if not path.exists():
        raise LimaAiError("restore", f"backup not found: {path}")
    return path, f"{GUEST_BACKUPS}/{relative.as_posix()}"


def _guest_listing(feature: Feature) -> tuple[set[str], str | None]:
    """Top-level names in the VM's working copy, and its .env if there is one."""
    out = feature.shell(["ls", "-1A"], workdir=feature.workdir, step="compose files").stdout
    names = set(out.splitlines())
    dotenv = None
    if ".env" in names:
        dotenv = feature.shell(["cat", ".env"], workdir=feature.workdir, step="compose files").stdout
    return names, dotenv


def _host_listing(root: Path) -> tuple[set[str], str | None]:
    if not root.is_dir():
        return set(), None
    names = {path.name for path in root.iterdir() if path.is_file()}
    dotenv = (root / ".env").read_text() if ".env" in names else None
    return names, dotenv


def run_backup(
    feature: Feature, full: bool, no_images: bool, no_external: bool, explicit: Sequence[str]
) -> None:
    if full and (no_external or explicit):
        raise LimaAiError("backup", "--no-external and --compose-file cannot be combined with --full")
    feature.running_instance()
    names, dotenv = _guest_listing(feature)
    where = f"the VM's ~/{feature.names.workdir}"
    files = compose_files(explicit, names, dotenv, required=not full, where=where)
    name = backup_name(feature.names.slug, feature.names.feat, full)
    dest = f"{GUEST_BACKUPS}/{name}"

    def in_vm(argv: list[str], **kwargs):
        return feature.shell(argv, workdir=feature.workdir, **kwargs)

    if files:
        note("==> Stopping the compose stack (volumes are read live)")
        in_vm(compose_argv(files, "stop"), step="compose stop")
    else:
        note("Note: no compose file, so no stack to stop; running containers' volumes are read live.")
    try:
        in_vm(backup_argv(files, dest, full, no_images, no_external), interactive=True, step="backup")
    finally:
        if files:
            note("==> Starting the compose stack again")
            in_vm(compose_argv(files, "start"), step="compose start")
    in_vm(["docker-backup", "info", dest], interactive=True, step="backup info")

    host_files = list(explicit)
    if not host_files:
        host_names, host_dotenv = _host_listing(feature.cfg.developer_dir / feature.names.project)
        host_files = detect_compose_files(host_names, host_dotenv) or files
    click.echo(f"\nBackup written to {feature.cfg.backups_dir / name}")
    click.echo("To bring it into the host's Colima:")
    for line in host_commands(
        feature.cfg, feature.names.project, host_files, bool(explicit), name, full, no_external
    ):
        click.echo(f"  {line}")


def run_restore(
    feature: Feature, backup: str, overwrite: bool, full: bool, explicit: Sequence[str]
) -> None:
    if full and explicit:
        raise LimaAiError("restore", "--compose-file cannot be combined with --full")
    _, source = resolve_backup(feature.cfg, backup)
    feature.running_instance()

    def in_vm(argv: list[str], **kwargs):
        return feature.shell(argv, workdir=feature.workdir, **kwargs)

    info = in_vm(["docker-backup", "info", "--json", source], step="backup info")
    try:
        manifest = json.loads(info.stdout)
    except json.JSONDecodeError:
        manifest = {}
    if isinstance(manifest, dict) and manifest.get("type") == "volume":
        raise LimaAiError(
            "restore",
            f"{backup} is a single-volume archive, which lima-ai does not restore. Restore it by hand: "
            f"`{feature.hint('shell')}`, then `docker-backup restore-volume {source} [--as NAME]`",
        )
    in_vm(["docker-backup", "info", source], interactive=True, step="backup info")

    if overwrite:
        click.confirm(
            "--overwrite: every volume the project uses that already exists in the VM, external ones "
            "included, will be emptied and refilled from the backup. Continue?",
            abort=True,
            err=True,
        )
    names, dotenv = _guest_listing(feature)
    stack = compose_files(explicit, names, dotenv, required=False, where="")
    if stack:
        note("==> Stopping the compose stack")
        in_vm(compose_argv(stack, "stop"), step="compose stop")
    result = in_vm(
        restore_argv([] if full else stack, source, overwrite), interactive=True, check=False, step="restore"
    )
    note(
        'Note: compose will warn "volume ... was not created by Docker Compose". That is harmless: '
        "restored volumes lack compose labels, and compose mounts the restored data anyway."
    )
    code = result.returncode
    if code == 0:
        if stack:
            note("==> Starting the compose stack")
            in_vm(compose_argv(stack, "up", "-d"), step="compose up")
        click.echo("Restore complete.")
    elif code in (2, 3):
        if stack:
            in_vm(compose_argv(stack, "start"), step="compose start")
        raise LimaAiError(
            "restore",
            f"docker-backup exited {code}, so nothing was changed (declined at the prompt, nothing for "
            "this project in the backup, or docker/compose unavailable); the stack was started again",
        )
    else:
        raise LimaAiError(
            "restore",
            f"docker-backup exited {code}: an item failed part-way. A volume created or emptied before "
            "the failure may be partly filled; rerun with --overwrite to refill it. "
            "The compose stack is left stopped.",
        )


def restore_step(feature: Feature, backup: str) -> Callable[[], None]:
    """`new --restore`: check the backup path now, restore (never --overwrite) once the VM is ready."""
    resolve_backup(feature.cfg, backup)
    return lambda: run_restore(feature, backup, overwrite=False, full=False, explicit=())
