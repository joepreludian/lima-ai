from pathlib import Path

import pytest

from lima_ai.errors import LimaAiError
from lima_ai.limactl import Limactl, gib
from tests.fakes import FakeRunner, lima_list


def test_list_parses_one_json_object_per_line():
    runner = FakeRunner().on("limactl list --json", lima_list(("dev-base", "Stopped"), ("dev-a-b", "Running")))
    instances = Limactl(runner).list()
    assert [(i.name, i.status, i.running) for i in instances] == [
        ("dev-base", "Stopped", False),
        ("dev-a-b", "Running", True),
    ]
    assert instances[1].ssh_config == Path("/Users/jon/.lima/dev-a-b/ssh.config")


def test_list_with_no_instances_is_empty():
    assert Limactl(FakeRunner()).list() == []


def test_get_finds_by_name_or_none():
    runner = FakeRunner().on("limactl list --json", lima_list(("dev-base", "Stopped")))
    lima = Limactl(runner)
    assert lima.get("dev-base").name == "dev-base"
    assert lima.get("dev-x-y") is None


def test_clone_passes_resource_overrides_in_gib():
    runner = FakeRunner()
    Limactl(runner).clone("dev-base", "dev-a-b", cpus=2, memory="16GiB", disk="100")
    assert runner.commands == ["limactl clone --tty=false dev-base dev-a-b --cpus 2 --memory 16 --disk 100"]


def test_clone_without_overrides():
    runner = FakeRunner()
    Limactl(runner).clone("dev-base", "dev-a-b")
    assert runner.commands == ["limactl clone --tty=false dev-base dev-a-b"]


def test_shell_puts_flags_before_instance_and_command_after():
    runner = FakeRunner()
    Limactl(runner).shell("dev-a-b", ["git", "status"], workdir="/home/jon.linux/work/a")
    assert runner.commands == ["limactl shell --workdir /home/jon.linux/work/a dev-a-b git status"]


def test_home_reads_guest_home():
    runner = FakeRunner().on("printenv HOME", "/home/jon.linux\n")
    assert Limactl(runner).home("dev-a-b") == "/home/jon.linux"


@pytest.mark.parametrize(
    "value, expected",
    [("8GiB", "8"), ("8", "8"), ("4.5GiB", "4.5"), ("16G", "16"), (" 2 GiB ", "2")],
)
def test_gib_accepts_gib_values(value, expected):
    assert gib(value) == expected


@pytest.mark.parametrize("value", ["8MiB", "lots", "", "-1GiB", "8TiB"])
def test_gib_rejects_other_values(value):
    with pytest.raises(LimaAiError):
        gib(value)
