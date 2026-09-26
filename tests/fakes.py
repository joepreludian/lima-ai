import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lima_ai.runner import raise_for_exit


@dataclass
class Call:
    argv: list[str]
    input: str | None
    interactive: bool
    cwd: Path | None

    @property
    def command(self) -> str:
        return shlex.join(self.argv)


class FakeRunner:
    """Records commands; answers them from rules matched on the joined command line."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._rules: list[tuple[str, int, str, str]] = []

    def on(self, pattern: str, stdout: str = "", returncode: int = 0, stderr: str = "") -> "FakeRunner":
        """Commands containing `pattern` get this result; later rules win."""
        self._rules.append((pattern, returncode, stdout, stderr))
        return self

    def run(self, argv, input=None, check=True, interactive=False, step=None, cwd=None):
        argv = [str(arg) for arg in argv]
        call = Call(argv, input, interactive, cwd)
        self.calls.append(call)
        returncode, stdout, stderr = 0, "", ""
        for pattern, rule_rc, rule_out, rule_err in reversed(self._rules):
            if pattern in call.command:
                returncode, stdout, stderr = rule_rc, rule_out, rule_err
                break
        if check and returncode != 0:
            raise_for_exit(step or Path(argv[0]).name, argv, returncode, stderr)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    @property
    def commands(self) -> list[str]:
        return [call.command for call in self.calls]

    def find(self, pattern: str) -> list[Call]:
        return [call for call in self.calls if pattern in call.command]


def lima_list(*instances: tuple[str, str]) -> str:
    """`limactl list --json` output for (name, status) pairs."""
    lines = []
    for name, status in instances:
        lima_dir = f"/Users/jon/.lima/{name}"
        lines.append(
            json.dumps(
                {
                    "name": name,
                    "status": status,
                    "dir": lima_dir,
                    "sshConfigFile": f"{lima_dir}/ssh.config",
                    "hostname": f"lima-{name}",
                }
            )
        )
    return "\n".join(lines) + ("\n" if lines else "")
