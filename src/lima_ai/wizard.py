"""The interactive side of `lima-ai new`: filling in what the command line left out."""

import shutil
from dataclasses import dataclass

import click

from lima_ai.config import Config
from lima_ai.errors import LimaAiError
from lima_ai.naming import check_project, resolve
from lima_ai.picker import pick_with_fzf
from lima_ai.runner import Runner


def note(message: str) -> None:
    click.echo(message, err=True)


@dataclass(frozen=True)
class Request:
    project: str  # relative to developer_dir, checked to exist
    workspace: str  # resolve() sanitises it again; it is already the sanitised form when prompted
    branch: str | None  # None: no branch step in the VM


def has_git(cfg: Config, project: str) -> bool:
    """A .git directory, or the .git file a worktree carries."""
    return (cfg.developer_dir / project / ".git").exists()


def fill(
    cfg: Config,
    runner: Runner,
    interactive: bool,
    project: str | None,
    workspace: str | None,
    branch: str | None,
    no_branch: bool,
) -> Request:
    if branch and no_branch:
        raise LimaAiError("usage", "--branch and --no-branch cannot be combined")
    if branch == "":
        raise LimaAiError("usage", "--branch needs a branch name")
    if (project is None or workspace is None) and not interactive:
        raise LimaAiError("usage", "PROJECT and WORKSPACE are required outside a terminal")
    if project is None:
        project = choose_project(cfg, runner)
    project = check_project(cfg.developer_dir, project)
    git = has_git(cfg, project)
    if not git:
        note(
            f"warning: {cfg.developer_dir / project} is not a git repository; no branch will be created "
            "and destroy cannot check it for unsaved work"
        )
    workspace = ask_workspace(cfg, project) if workspace is None else clean_workspace(cfg, project, workspace)
    if not git or no_branch:
        branch = None
    elif branch is None:
        branch = ask_branch(workspace) if interactive else workspace
    return Request(project=project, workspace=workspace, branch=branch)


def choose_project(cfg: Config, runner: Runner) -> str:
    """Pick the project with fzf when it is installed, otherwise ask for the folder until it exists."""
    if shutil.which("fzf"):
        return check_project(cfg.developer_dir, pick_with_fzf(cfg, runner))
    note("tip: install fzf (brew install fzf) to pick the project from a list")
    while True:
        answer = click.prompt(f"Project folder (relative to {cfg.developer_dir})", err=True)
        try:
            return check_project(cfg.developer_dir, answer)
        except LimaAiError as err:
            note(f"error [{err.step}]: {err.message}")


def ask_workspace(cfg: Config, project: str) -> str:
    """Ask for a workspace name until it survives sanitising and the hostname limit."""
    while True:
        raw = click.prompt("Workspace name", err=True)
        try:
            return clean_workspace(cfg, project, raw)
        except LimaAiError as err:
            note(f"error [{err.step}]: {err.message}")


def clean_workspace(cfg: Config, project: str, raw: str) -> str:
    """The sanitised workspace name (noted when it differs), so the branch default and the VM name agree."""
    workspace = resolve(cfg.developer_dir, project, raw).workspace
    if workspace != raw:
        note(f"using workspace name {workspace}")
    return workspace


def ask_branch(workspace: str) -> str:
    return click.prompt("Git branch", default=workspace, err=True)
