"""Picking the project folder for `lima-ai new`: a walk of developer_dir, offered through fzf."""

import os
from pathlib import Path

import click

from lima_ai.config import Config
from lima_ai.errors import LimaAiError
from lima_ai.render import rsync_excludes
from lima_ai.runner import Runner

GIT_MARKER = "  (git)"
MAX_DEPTH = 3


def candidates(cfg: Config) -> list[tuple[str, bool]]:
    """(path relative to developer_dir, is a git repo) for every pickable folder, sorted, depth-first."""
    root = cfg.developer_dir
    if not root.is_dir():
        raise LimaAiError("project", f"{root} does not exist; set developer_dir in config.toml")
    skip = {line.rstrip("/") for line in rsync_excludes(cfg).splitlines() if line}
    found: list[tuple[str, bool]] = []

    def walk(folder: Path, depth: int) -> None:
        for entry in sorted(os.scandir(folder), key=lambda e: e.name):
            if not entry.is_dir(follow_symlinks=False) or entry.name.startswith(".") or entry.name in skip:
                continue
            sub = Path(entry.path)
            if sub == cfg.backups_dir or cfg.backups_dir in sub.parents:
                continue
            is_git = (sub / ".git").exists()
            found.append((sub.relative_to(root).as_posix(), is_git))
            if not is_git and depth < MAX_DEPTH:
                walk(sub, depth + 1)

    walk(root, 1)
    if not found:
        raise LimaAiError("project", f"no project folders under {root}")
    return found


def pick_with_fzf(cfg: Config, runner: Runner) -> str:
    """fzf draws on /dev/tty, so its stdout can be captured while it reads candidates from stdin."""
    lines = "".join(f"{path}{GIT_MARKER if is_git else ''}\n" for path, is_git in candidates(cfg))
    argv = ["fzf", "--prompt", "Project> ", "--height", "40%", "--reverse", "--no-multi"]
    result = runner.run(argv, input=lines, check=False, step="picker")
    choice = result.stdout.strip()
    if result.returncode != 0 or not choice:
        raise click.Abort()
    return choice.removesuffix(GIT_MARKER)
