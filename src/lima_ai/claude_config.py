import copy
import json
import re
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import click

from lima_ai.errors import LimaAiError
from lima_ai.limactl import Instance
from lima_ai.runner import Runner
from lima_ai.sync import rsync_argv, ssh_host

# What is copied from the host ~/.claude; everything else (history, projects,
# sessions, caches, credentials, ...) stays on the host.
INCLUDE_FILES = ("CLAUDE.md", "RTK.md", "settings.json", "statusline-command.sh")
INCLUDE_DIRS = ("skills", "plugins", "commands", "agents")
INCLUDE = INCLUDE_FILES + INCLUDE_DIRS

# Characters that end a path inside a shell command.
_PATH_CHARS = r"[^\s'\";|&()<>]*"


def filter_options() -> list[str]:
    """rsync filters copying the include list, minus the files stage_transformed writes."""
    options = ["--exclude=*.bak", "--exclude=/settings.json", "--exclude=/plugins/*.json"]
    options += [f"--include=/{name}" for name in INCLUDE_FILES]
    for name in INCLUDE_DIRS:
        options += [f"--include=/{name}/", f"--include=/{name}/**"]
    options.append("--exclude=*")
    return options


def _home_relative(path: str, host_home: str) -> str | None:
    prefix = host_home.rstrip("/") + "/"
    if path == host_home.rstrip("/"):
        return ""
    return path[len(prefix) :] if path.startswith(prefix) else None


def _referenced_home_paths(command: str, host_home: str) -> list[str]:
    """Paths under the host home in a command, relative to it (/Users/x/…, ~/…, $HOME/…)."""
    prefixes = rf"{re.escape(host_home.rstrip('/'))}|(?<![\w~])~|\$HOME|\$\{{HOME\}}"
    return [match[1][1:] for match in re.finditer(rf"(?:{prefixes})(/{_PATH_CHARS})", command)]


def _available_in_guest(relative: str, developer_rel: str | None) -> bool:
    parts = relative.split("/")
    if parts[0] == ".claude" and len(parts) > 1 and parts[1] in INCLUDE:
        return True
    if developer_rel and (relative == developer_rel or relative.startswith(developer_rel + "/")):
        return True  # mounted read-only at the same path
    return False


@dataclass(frozen=True)
class HookChoice:
    """A host hook command the guest would lose, which the user may choose to copy in."""

    command: str  # as written in the host settings.json
    events: tuple[str, ...]  # where it is attached: "Stop", "PreToolUse (Bash)", ...
    files: tuple[str, ...]  # what it runs that the guest lacks, relative to the host home


def _missing_in_guest(command: str, host_home: str, developer_rel: str | None) -> list[str]:
    """Host-home paths in a command that the guest will not have, relative to the home."""
    paths = _referenced_home_paths(command, host_home)
    return list(dict.fromkeys(path for path in paths if not _available_in_guest(path, developer_rel)))


def offered_hooks(settings: dict, host_home: str, developer_dir: str) -> list[HookChoice]:
    """The hooks filter_hooks drops whose missing paths are all files on the host, one per command."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    developer_rel = _home_relative(developer_dir, host_home)
    events: dict[str, list[str]] = {}
    files: dict[str, tuple[str, ...]] = {}
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                continue
            matcher = group.get("matcher")
            label = f"{event} ({matcher})" if isinstance(matcher, str) and matcher not in ("", "*") else event
            for hook in group["hooks"]:
                command = hook.get("command") if isinstance(hook, dict) else None
                if not isinstance(command, str):
                    continue
                missing = _missing_in_guest(command, host_home, developer_rel)
                if not missing or not all((Path(host_home) / path).is_file() for path in missing):
                    continue
                files[command] = tuple(missing)
                seen = events.setdefault(command, [])
                if label not in seen:
                    seen.append(label)
    return [HookChoice(command, tuple(events[command]), files[command]) for command in events]


def display_command(command: str, host_home: str) -> str:
    """A hook command with the host home shown as `~`."""
    return command.replace(host_home.rstrip("/") + "/", "~/")


def filter_hooks(settings: dict, host_home: str, developer_dir: str, keep: Collection[str] = ()) -> dict:
    """Drop hooks that run host-home files the guest will not have; drop what is left empty.

    Commands in `keep` stay: the caller copies their files into the guest.
    """
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    developer_rel = _home_relative(developer_dir, host_home)

    def stays(hook) -> bool:
        command = hook.get("command") if isinstance(hook, dict) else None
        if not isinstance(command, str):
            return True  # not a command hook: nothing to judge
        return command in keep or not _missing_in_guest(command, host_home, developer_rel)

    # Anything not shaped like {event: [{hooks: [...]}]} is left as written.
    for event in list(hooks):
        if not isinstance(hooks[event], list):
            continue
        groups = []
        for group in hooks[event]:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                groups.append(group)
                continue
            kept = [hook for hook in group["hooks"] if stays(hook)]
            if kept:
                groups.append({**group, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    return result


def rewrite_home(text: str, host_home: str, guest_home: str, developer_dir: str) -> str:
    """Host home prefix → guest home, except under developer_dir, which the guest mounts as is."""
    developer_rel = _home_relative(developer_dir, host_home)
    keep = rf"(?!{re.escape(developer_rel)}(?![\w.-]))" if developer_rel else ""
    pattern = re.escape(host_home.rstrip("/") + "/") + keep
    return re.sub(pattern, guest_home.rstrip("/") + "/", text)


def read_settings(claude_dir: Path) -> dict:
    """The host settings.json; {} when there is none."""
    settings = claude_dir / "settings.json"
    if not settings.is_file():
        return {}
    try:
        data = json.loads(settings.read_text())
    except json.JSONDecodeError as exc:
        raise LimaAiError("sync-claude", f"{settings} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise LimaAiError("sync-claude", f"{settings} is not a JSON object")
    return data


def stage_transformed(
    claude_dir: Path,
    staging: Path,
    host_home: str,
    guest_home: str,
    developer_dir: str,
    keep: Collection[str] = (),
) -> None:
    """Write the transformed settings.json and plugins/*.json into staging."""
    staging.mkdir(parents=True, exist_ok=True)
    if (claude_dir / "settings.json").is_file():
        data = read_settings(claude_dir)
        text = json.dumps(filter_hooks(data, host_home, developer_dir, keep), indent=2) + "\n"
        target = staging / "settings.json"
        target.write_text(rewrite_home(text, host_home, guest_home, developer_dir))
        target.chmod(0o600)
    plugins = claude_dir / "plugins"
    for source in sorted(plugins.glob("*.json")) if plugins.is_dir() else []:
        target = staging / "plugins" / source.name
        target.parent.mkdir(exist_ok=True)
        target.write_text(rewrite_home(source.read_text(), host_home, guest_home, developer_dir))


def push_claude_config(
    runner: Runner,
    instance: Instance,
    guest_home: str,
    developer_dir: Path,
    host_home: Path,
    keep_hooks: Collection[str] = (),
) -> None:
    """Copy the Claude config; `keep_hooks` are hook commands whose scripts go along."""
    claude_dir = host_home / ".claude"
    if not claude_dir.is_dir():
        click.echo(f"    {claude_dir} not found; skipping Claude config", err=True)
        return
    dest = f"{ssh_host(instance.name)}:.claude/"
    # Only what is still offered: a saved command whose script is gone from the host is dropped as before.
    offered = offered_hooks(read_settings(claude_dir), str(host_home), str(developer_dir)) if keep_hooks else []
    kept = [choice for choice in offered if choice.command in keep_hooks]
    keep = {choice.command for choice in kept}
    with tempfile.TemporaryDirectory(prefix="lima-ai-claude-") as tmp:
        staging = Path(tmp)
        stage_transformed(claude_dir, staging, str(host_home), guest_home, str(developer_dir), keep)
        # No --delete: sessions and history created in the guest survive re-syncs.
        runner.run(
            rsync_argv([f"{claude_dir}/"], dest, instance.ssh_config, ["--copy-unsafe-links", *filter_options()]),
            step="sync-claude",
        )
        if kept:
            # Paths relative to the host home, so each script lands at the same place under the guest home.
            # openrsync ignores the /./ anchor, hence cwd.
            files = sorted({path for choice in kept for path in choice.files})
            home_dest = f"{ssh_host(instance.name)}:"
            runner.run(
                rsync_argv(files, home_dest, instance.ssh_config, ["--relative", "--copy-links"]),
                step="sync-claude",
                cwd=host_home,
            )
            shown = ", ".join(display_command(choice.command, str(host_home)) for choice in kept)
            click.echo(f"    hooks kept: {shown}", err=True)
        runner.run(rsync_argv([f"{staging}/"], dest, instance.ssh_config, []), step="sync-claude")
