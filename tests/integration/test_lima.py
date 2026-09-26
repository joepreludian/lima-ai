"""End-to-end tests against real Lima VMs (opt-in: `pytest -m lima`, slow).

They build dev-base if it is missing, create dev-limaaitest-* VMs from a
fixture compose project (a `build:` service with a named volume) and delete
them afterwards, together with the backups they wrote. The CLI runs under
`script` so docker-backup gets the terminal its confirmation prompt needs.
"""

import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

from lima_ai.config import load_config

pytestmark = pytest.mark.lima

FIXTURE = Path(__file__).parent / "fixture"
PROJECT = "limaaitest"
OTHER_PROJECT = "limaaitest2"
INSTANCES = [f"dev-{PROJECT}-a", f"dev-{PROJECT}-b", f"dev-{PROJECT}-c", f"dev-{OTHER_PROJECT}-d"]
# click's and docker-backup's confirmation prompts.
PROMPT = re.compile(r"\[y/N\]")


class Lab:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.developer = root / "Developer"
        self.home = root / "home"
        self.backups_dir = load_config().backups_dir
        self.build_id = uuid.uuid4().hex
        self.backups: list[str] = []
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "LIMA_HOME": os.environ.get("LIMA_HOME", str(Path.home() / ".lima")),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_STATE_HOME": str(root / "state"),
        }

    def setup(self) -> None:
        for name in (PROJECT, OTHER_PROJECT):
            shutil.copytree(FIXTURE, self.developer / name)
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude/CLAUDE.md").write_text("# integration test\n")
        (self.home / ".gitconfig").write_text("[user]\n\tname = lima-ai test\n\temail = test@example.com\n")
        config = self.root / "config/lima-ai"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(f'developer_dir = "{self.developer}"\nbackups_dir = "{self.backups_dir}"\n')
        (config / "oauth-token").write_text("integration-test-token\n")
        (config / "oauth-token").chmod(0o600)

    def cli(self, *args: str, confirm: bool = False, timeout: int = 1800) -> str:
        """Run lima-ai on a pty; with confirm, answer each [y/N] prompt with y as it appears.

        Answers written before a prompt is shown are lost to the pty, so this
        reads the output as it comes instead of piping answers up front.
        """
        command = ["script", "-q", "/dev/null", sys.executable, "-m", "lima_ai", *args]
        proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env
        )
        output, answered = b"", 0
        deadline = time.monotonic() + timeout
        fd = proc.stdout.fileno()
        while True:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                output += chunk
                prompts = len(PROMPT.findall(output.decode(errors="replace")))
                while answered < prompts:
                    proc.stdin.write(b"y\n" if confirm else b"n\n")
                    proc.stdin.flush()
                    answered += 1
            if time.monotonic() > deadline:
                proc.kill()
                raise AssertionError(f"{args} timed out:\n{output.decode(errors='replace')}")
        proc.wait()
        text = output.decode(errors="replace").replace("\r\n", "\n")
        assert proc.returncode == 0, f"{args} failed:\n{text}"
        return text

    def vm(self, instance: str, script: str, workdir: str | None = None) -> str:
        argv = ["limactl", "shell"]
        if workdir:
            argv += ["--workdir", workdir]
        result = subprocess.run(
            [*argv, instance, "bash", "-c", script], env=self.env, capture_output=True, text=True, timeout=600
        )
        assert result.returncode == 0, f"{script} failed in {instance}:\n{result.stderr}"
        return result.stdout.strip()

    def compose(self, instance: str, slug: str, script: str) -> str:
        home = self.vm(instance, "printenv HOME")
        return self.vm(instance, script, workdir=f"{home}/work/{slug}")

    def backup(self, *args: str) -> str:
        output = self.cli("backup", *args)
        line = next(line for line in output.splitlines() if line.startswith("Backup written to "))
        name = Path(line.removeprefix("Backup written to ").strip()).name
        self.backups.append(name)
        return name

    def cleanup(self) -> None:
        for instance in INSTANCES:
            subprocess.run(["limactl", "delete", "-f", instance], env=self.env, capture_output=True)
        for name in self.backups:
            path = self.backups_dir / name
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    lab = Lab(tmp_path_factory.mktemp("lima-ai"))
    lab.setup()
    yield lab
    lab.cleanup()


def served(instance: str) -> str:
    with urllib.request.urlopen(f"http://lima-{instance}.local:8002/", timeout=10) as response:
        return response.read().decode().strip()


def image_build_id(lab: Lab, instance: str, slug: str) -> str:
    return lab.vm(
        instance,
        f"docker image inspect {slug}-web --format '{{{{index .Config.Labels \"lima-ai-test.build-id\"}}}}'",
    )


def volume_content(lab: Lab, instance: str, volume: str) -> str:
    return lab.vm(instance, f"docker run --rm -v {volume}:/data alpine:3 cat /data/index.html")


def test_base_is_built_verified_and_sealed(lab):
    listed = subprocess.run(["limactl", "list", "--json"], env=lab.env, capture_output=True, text=True)
    names = [json.loads(line)["name"] for line in listed.stdout.splitlines() if line.strip()]
    if "dev-base" not in names:
        lab.cli("base")
    listed = subprocess.run(["limactl", "list", "--json", "dev-base"], env=lab.env, capture_output=True, text=True)
    assert json.loads(listed.stdout)["status"] == "Stopped"


def test_two_clones_serve_their_own_content_on_the_same_port(lab):
    for feat in ("a", "b"):
        lab.cli("new", PROJECT, feat)
        instance = f"dev-{PROJECT}-{feat}"
        lab.compose(
            instance,
            PROJECT,
            f"BUILD_ID={lab.build_id} docker compose up -d --build && "
            f"docker compose exec -T web sh -c 'echo clone-{feat} > /data/index.html'",
        )
    ip_a = socket.gethostbyname(f"lima-dev-{PROJECT}-a.local")
    ip_b = socket.gethostbyname(f"lima-dev-{PROJECT}-b.local")
    assert ip_a != ip_b
    assert served(f"dev-{PROJECT}-a") == "clone-a"
    assert served(f"dev-{PROJECT}-b") == "clone-b"
    ls = lab.cli("ls")
    assert f"lima-dev-{PROJECT}-a.local" in ls and ip_a in ls


def test_clone_has_the_full_toolchain(lab):
    from lima_ai.render import guest_script

    lab.vm(f"dev-{PROJECT}-a", guest_script("verify-base.sh"))


def test_backup_restores_into_a_new_clone_with_its_built_image(lab):
    name = lab.backup(PROJECT, "a")
    lab.cli("new", PROJECT, "c", "--restore", name, confirm=True)
    instance = f"dev-{PROJECT}-c"
    assert volume_content(lab, instance, f"{PROJECT}_data") == "clone-a"
    assert image_build_id(lab, instance, PROJECT) == lab.build_id, "the image was rebuilt, not restored"
    assert served(instance) == "clone-a"
    lab.backups_for_later = name


def test_restore_maps_volume_and_image_to_another_project_name(lab):
    name = lab.backups_for_later
    lab.cli("new", OTHER_PROJECT, "d")
    lab.cli("restore", OTHER_PROJECT, "d", name, confirm=True)
    instance = f"dev-{OTHER_PROJECT}-d"
    assert volume_content(lab, instance, f"{OTHER_PROJECT}_data") == "clone-a"
    assert image_build_id(lab, instance, OTHER_PROJECT) == lab.build_id


def test_restore_with_overwrite_brings_the_backup_data_back(lab):
    name = lab.backups_for_later
    instance = f"dev-{PROJECT}-a"
    lab.compose(instance, PROJECT, "docker compose exec -T web sh -c 'echo changed > /data/index.html'")
    assert served(instance) == "changed"
    lab.cli("restore", PROJECT, "a", name, "--overwrite", confirm=True)
    assert volume_content(lab, instance, f"{PROJECT}_data") == "clone-a"


def test_full_backup_round_trip(lab):
    instance = f"dev-{PROJECT}-b"
    name = lab.backup(PROJECT, "b", "--full")
    assert "-full-" in name
    lab.compose(instance, PROJECT, "docker compose exec -T web sh -c 'echo changed > /data/index.html'")
    lab.cli("restore", PROJECT, "b", name, "--full", "--overwrite", confirm=True)
    assert volume_content(lab, instance, f"{PROJECT}_data") == "clone-b"


def test_rm_deletes_the_vm(lab):
    lab.cli("rm", OTHER_PROJECT, "d", "--force")
    listed = subprocess.run(["limactl", "list", "--json"], env=lab.env, capture_output=True, text=True)
    assert f"dev-{OTHER_PROJECT}-d" not in listed.stdout
