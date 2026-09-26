import re
import shlex
from pathlib import Path

from lima_ai.runner import Runner


def ssh_host(instance: str) -> str:
    """The Host alias in Lima's per-instance ssh.config."""
    return f"lima-{instance}"


def progress_flags(runner: Runner) -> list[str]:
    """--info=progress2 needs GNU rsync ≥ 3.1; macOS ships openrsync, which rejects it."""
    out = runner.run(["rsync", "--version"], step="rsync").stdout
    first_line = out.splitlines()[0] if out else ""
    if "openrsync" not in first_line:
        match = re.search(r"version (\d+)\.(\d+)", first_line)
        if match and (int(match[1]), int(match[2])) >= (3, 1):
            return ["--info=progress2"]
    return ["--stats"]


def rsync_argv(sources: list[str], dest: str, ssh_config: Path, options: list[str]) -> list[str]:
    return ["rsync", "-a", *options, "-e", f"ssh -F {shlex.quote(str(ssh_config))}", *sources, dest]


def project_argv(
    src_dir: Path,
    instance: str,
    workdir: str,
    ssh_config: Path,
    exclude_file: Path,
    progress: list[str],
) -> list[str]:
    """Copy the project's contents into the guest working copy. No --delete, ever."""
    return rsync_argv(
        [f"{src_dir}/"],
        f"{ssh_host(instance)}:{workdir}/",
        ssh_config,
        [*progress, f"--exclude-from={exclude_file}"],
    )
