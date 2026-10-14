import platform
import re
import shutil
from dataclasses import dataclass

import click

from lima_ai import auth
from lima_ai.config import load_config
from lima_ai.errors import LimaAiError
from lima_ai.limactl import Limactl
from lima_ai.naming import BASE_INSTANCE
from lima_ai.runner import Runner

TOOL_HINTS = {
    "limactl": "install Lima: brew install lima",
    "rsync": "rsync ships with macOS; check your PATH",
    "claude": "install Claude Code: https://docs.claude.com/en/docs/claude-code",
    "docker-backup": "brew install joepreludian/tap/docker-backup",
}
MIN_LIMA = (2, 0)
MIN_DOCKER_BACKUP = (0, 4, 0)
STYLES = {"ok": "green", "warn": "yellow", "fail": "red", "skip": "bright_black"}


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok, warn, fail or skip
    detail: str = ""
    fix: str = ""


def run_checks(runner: Runner, system: str | None = None, machine: str | None = None) -> list[Check]:
    """Every check, in the order `doctor` prints them; none of them raises."""
    system = system or platform.system()
    machine = machine or platform.machine()
    return [
        check_platform(system),
        check_rosetta(runner, system, machine),
        check_limactl(runner),
        check_tool("rsync"),
        check_tool("claude"),
        check_ssh_agent(runner),
        check_config(),
        check_token(),
        check_dev_base(runner),
        check_docker_backup(runner),
    ]


def check_platform(system: str) -> Check:
    if system in ("Darwin", "Linux"):
        return Check("platform", "ok", system)
    return Check("platform", "fail", system, "lima-ai runs on macOS or Linux")


def check_rosetta(runner: Runner, system: str, machine: str) -> Check:
    if (system, machine) != ("Darwin", "arm64"):
        return Check("Rosetta", "skip", "Apple Silicon only")
    if runner.run(["arch", "-x86_64", "/usr/bin/true"], check=False).returncode == 0:
        return Check("Rosetta", "ok")
    return Check("Rosetta", "fail", fix="softwareupdate --install-rosetta --agree-to-license")


def check_tool(tool: str) -> Check:
    if shutil.which(tool):
        return Check(tool, "ok")
    return Check(tool, "fail", "not found on PATH", TOOL_HINTS[tool])


def check_limactl(runner: Runner) -> Check:
    return _check_version(runner, "limactl", MIN_LIMA, "fail", "brew upgrade lima")


def check_docker_backup(runner: Runner) -> Check:
    return _check_version(runner, "docker-backup", MIN_DOCKER_BACKUP, "warn", "brew upgrade docker-backup")


def _check_version(runner: Runner, tool: str, minimum: tuple[int, ...], severity: str, upgrade: str) -> Check:
    name = f"{tool} (>= {'.'.join(map(str, minimum))})"
    if not shutil.which(tool):
        return Check(name, severity, "not found on PATH", TOOL_HINTS[tool])
    out = runner.run([tool, "--version"], check=False).stdout
    match = re.search(r"\d+(?:\.\d+)+", out)
    if not match:
        return Check(name, severity, "unknown version", upgrade)
    found = match.group(0)
    if tuple(int(part) for part in found.split(".")) < minimum:
        return Check(name, severity, found, upgrade)
    return Check(name, "ok", found)


def check_ssh_agent(runner: Runner) -> Check:
    name = "ssh-agent key"
    if not shutil.which("ssh-add"):
        return Check(name, "fail", "ssh-add not found on PATH", "install OpenSSH")
    result = runner.run(["ssh-add", "-l"], check=False)
    keys = len(result.stdout.strip().splitlines()) if result.returncode == 0 else 0
    if keys:
        return Check(name, "ok", f"{keys} key" + ("s" if keys > 1 else ""))
    return Check(name, "fail", "no key loaded", "ssh-add ~/.ssh/<your key>")


def check_config() -> Check:
    try:
        load_config()
    except LimaAiError as err:
        return Check("config.toml", "fail", "invalid", f"fix config.toml: {err.message}")
    return Check("config.toml", "ok")


def check_token() -> Check:
    if auth.token_path().is_file():
        return Check("Claude token", "ok")
    return Check("Claude token", "fail", "missing", "lima-ai auth")


def check_dev_base(runner: Runner) -> Check:
    if not shutil.which("limactl"):
        return Check(BASE_INSTANCE, "skip", "needs limactl")
    try:
        base = Limactl(runner).get(BASE_INSTANCE)
    except LimaAiError as err:
        return Check(BASE_INSTANCE, "warn", "limactl list failed", err.message)
    if base is None:
        return Check(BASE_INSTANCE, "warn", "not built", "lima-ai base")
    if base.running:
        return Check(BASE_INSTANCE, "warn", "running", f"limactl stop {BASE_INSTANCE}")
    return Check(BASE_INSTANCE, "ok", base.status)


def render(checks: list[Check]) -> str:
    """A status table, then a table of problems with their fixes (if any)."""
    lines = _table(("Check", "Status", ""), [(c.name, c.status, c.detail) for c in checks], style_column=1)
    problems = [c for c in checks if c.status in ("fail", "warn")]
    fails = sum(c.status == "fail" for c in checks)
    warns = len(problems) - fails
    if problems:
        lines.append("")
        lines += _table(("Problem", "Fix"), [(c.name, c.fix) for c in problems])
        lines.append("")
        lines.append(f"{_plural(fails, 'problem')}, {_plural(warns, 'warning')}.")
    else:
        lines.append("")
        lines.append("All checks passed.")
    return "\n".join(lines) + "\n"


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]], style_column: int | None = None) -> list[str]:
    """Padded columns; cells in `style_column` are coloured by status (padding first, so colour codes don't count)."""
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]

    def line(row: tuple[str, ...], styled: bool) -> str:
        cells = [cell.ljust(width) for cell, width in zip(row, widths, strict=True)]
        if styled and style_column is not None:
            cells[style_column] = click.style(cells[style_column], fg=STYLES.get(row[style_column]))
        return "  " + "  ".join(cells).rstrip()

    return [click.style(line(header, False), bold=True), *(line(row, True) for row in rows)]


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")
