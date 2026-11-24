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
    if branch:
        check_branch_switch(cfg, runner, project, branch)
    return Request(project=project, workspace=workspace, branch=branch)


def check_branch_switch(cfg: Config, runner: Runner, project: str, branch: str) -> None:
    """Fail now when `git switch <branch>` is sure to fail in the VM.

    The VM gets the host's working copy, uncommitted changes included, and switches there. Git refuses
    when the branch exists, is not the one checked out, and a file with uncommitted changes (or an
    untracked one) differs between the two. A new branch carries the changes along, so it passes.
    """
    git = ["git", "-C", str(cfg.developer_dir / project)]

    def names(*args: str) -> set[str]:
        out = runner.run([*git, *args], check=False, step="preflight")
        return set(filter(None, out.stdout.split("\0"))) if out.returncode == 0 else set()

    exists = runner.run([*git, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
    if exists.returncode != 0:
        return
    current = runner.run([*git, "symbolic-ref", "-q", "--short", "HEAD"], check=False)
    if current.returncode == 0 and current.stdout.strip() == branch:
        return
    diff = ("diff", "--name-only", "--no-renames", "-z", "HEAD")
    between = names(*diff, branch)
    changed = names(*diff, "--") | names("ls-files", "--others", "--exclude-standard", "-z")
    blocking = sorted(between & changed)
    if blocking:
        files = "\n".join(f"  {name}" for name in blocking)
        raise LimaAiError(
            "preflight",
            f"cannot switch to {branch} in the VM: these files have uncommitted changes and differ on {branch}:\n"
            f"{files}\n"
            "Commit or stash them, choose another branch with --branch, "
            "or keep the current branch with --no-branch.",
        )


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
