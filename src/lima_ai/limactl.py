import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lima_ai.errors import LimaAiError
from lima_ai.runner import Runner


@dataclass(frozen=True)
class Instance:
    name: str
    status: str
    dir: Path
    ssh_config: Path

    @property
    def running(self) -> bool:
        return self.status == "Running"


def gib(value: str) -> str:
    """'8GiB', '8G' or '8' → '8', the plain GiB number `limactl clone` takes."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:GiB|G)?\s*", value)
    if not match:
        raise LimaAiError("naming", f"size '{value}' must be in GiB, e.g. 8GiB")
    return match.group(1)


class Limactl:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner

    def list(self) -> list[Instance]:
        out = self.runner.run(["limactl", "list", "--json"], step="limactl list").stdout
        instances = []
        for line in out.splitlines():
            if line.strip():
                data = json.loads(line)
                instances.append(
                    Instance(
                        name=data["name"],
                        status=data["status"],
                        dir=Path(data["dir"]),
                        ssh_config=Path(data["sshConfigFile"]),
                    )
                )
        return instances

    def get(self, name: str) -> Instance | None:
        return next((i for i in self.list() if i.name == name), None)

    def create_and_start(self, name: str, template: Path) -> None:
        self.runner.run(
            ["limactl", "start", "--name", name, "--tty=false", template], interactive=True, step="start"
        )

    def start(self, name: str) -> None:
        self.runner.run(["limactl", "start", "--tty=false", name], interactive=True, step="start")

    def stop(self, name: str) -> None:
        self.runner.run(["limactl", "stop", name], step="stop")

    def delete(self, name: str) -> None:
        self.runner.run(["limactl", "delete", "-f", name], step="delete")

    def clone(
        self,
        source: str,
        name: str,
        cpus: int | None = None,
        memory: str | None = None,
        disk: str | None = None,
    ) -> None:
        argv = ["limactl", "clone", "--tty=false", source, name]
        if cpus is not None:
            argv += ["--cpus", str(cpus)]
        if memory is not None:
            argv += ["--memory", gib(memory)]
        if disk is not None:
            argv += ["--disk", gib(disk)]
        self.runner.run(argv, step="clone")

    def shell(
        self,
        name: str,
        argv: Sequence[str],
        workdir: str | None = None,
        input: str | None = None,
        check: bool = True,
        interactive: bool = False,
        step: str | None = None,
    ) -> subprocess.CompletedProcess:
        command = ["limactl", "shell"]
        if workdir:
            command += ["--workdir", workdir]
        command += [name, *argv]
        return self.runner.run(command, input=input, check=check, interactive=interactive, step=step)

    def home(self, name: str) -> str:
        return self.shell(name, ["printenv", "HOME"], step="guest home").stdout.strip()
