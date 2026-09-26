import copy
import json
import re
import tempfile
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


def filter_hooks(settings: dict, host_home: str, developer_dir: str) -> dict:
    """Drop hooks that run host-home files the guest will not have; drop what is left empty."""
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    developer_rel = _home_relative(developer_dir, host_home)

    def keep(hook: dict) -> bool:
        command = hook.get("command", "")
        return all(_available_in_guest(path, developer_rel) for path in _referenced_home_paths(command, host_home))

    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [hook for hook in group.get("hooks", []) if keep(hook)]
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


def stage_transformed(claude_dir: Path, staging: Path, host_home: str, guest_home: str, developer_dir: str) -> None:
    """Write the transformed settings.json and plugins/*.json into staging."""
    staging.mkdir(parents=True, exist_ok=True)
    settings = claude_dir / "settings.json"
    if settings.is_file():
        try:
            data = json.loads(settings.read_text())
        except json.JSONDecodeError as exc:
            raise LimaAiError("sync-claude", f"{settings} is not valid JSON: {exc}") from None
        text = json.dumps(filter_hooks(data, host_home, developer_dir), indent=2) + "\n"
        target = staging / "settings.json"
        target.write_text(rewrite_home(text, host_home, guest_home, developer_dir))
        target.chmod(0o600)
    plugins = claude_dir / "plugins"
    for source in sorted(plugins.glob("*.json")) if plugins.is_dir() else []:
        target = staging / "plugins" / source.name
        target.parent.mkdir(exist_ok=True)
        target.write_text(rewrite_home(source.read_text(), host_home, guest_home, developer_dir))


def push_claude_config(
    runner: Runner, instance: Instance, guest_home: str, developer_dir: Path, host_home: Path
) -> None:
    claude_dir = host_home / ".claude"
    if not claude_dir.is_dir():
        click.echo(f"    {claude_dir} not found; skipping Claude config", err=True)
        return
    dest = f"{ssh_host(instance.name)}:.claude/"
    with tempfile.TemporaryDirectory(prefix="lima-ai-claude-") as tmp:
        staging = Path(tmp)
        stage_transformed(claude_dir, staging, str(host_home), guest_home, str(developer_dir))
        # No --delete: sessions and history created in the guest survive re-syncs.
        runner.run(
            rsync_argv([f"{claude_dir}/"], dest, instance.ssh_config, ["--copy-unsafe-links", *filter_options()]),
            step="sync-claude",
        )
        runner.run(rsync_argv([f"{staging}/"], dest, instance.ssh_config, []), step="sync-claude")
