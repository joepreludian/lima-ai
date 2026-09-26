from pathlib import Path

from lima_ai.sync import progress_flags, project_argv, rsync_argv, ssh_host
from tests.fakes import FakeRunner

SSH_CONFIG = Path("/Users/jon/.lima/dev-app-a/ssh.config")


def test_gnu_rsync_gets_progress2():
    runner = FakeRunner().on("rsync --version", "rsync  version 3.4.1  protocol version 32\n")
    assert progress_flags(runner) == ["--info=progress2"]


def test_openrsync_gets_stats_because_it_rejects_info():
    runner = FakeRunner().on("rsync --version", "openrsync: protocol version 29\nrsync version 2.6.9 compatible\n")
    assert progress_flags(runner) == ["--stats"]


def test_old_gnu_rsync_gets_stats():
    runner = FakeRunner().on("rsync --version", "rsync  version 2.6.9  protocol version 29\n")
    assert progress_flags(runner) == ["--stats"]


def test_ssh_host_is_limas_alias():
    assert ssh_host("dev-app-a") == "lima-dev-app-a"


def test_rsync_argv_uses_instance_ssh_config():
    argv = rsync_argv(["/src/"], "lima-dev-app-a:dest/", SSH_CONFIG, ["--stats"])
    assert argv == [
        "rsync",
        "-a",
        "--stats",
        "-e",
        f"ssh -F {SSH_CONFIG}",
        "/src/",
        "lima-dev-app-a:dest/",
    ]


def test_ssh_config_path_with_spaces_is_quoted():
    argv = rsync_argv(["/src/"], "h:d/", Path("/Users/j o/.lima/x/ssh.config"), [])
    assert argv[argv.index("-e") + 1] == "ssh -F '/Users/j o/.lima/x/ssh.config'"


def test_project_argv_copies_contents_into_workdir():
    argv = project_argv(
        Path("/Users/jon/Developer/preludian/app"),
        "dev-app-a",
        "work/app",
        SSH_CONFIG,
        Path("/state/rsync-exclude.txt"),
        ["--info=progress2"],
    )
    assert argv == [
        "rsync",
        "-a",
        "--info=progress2",
        "--exclude-from=/state/rsync-exclude.txt",
        "-e",
        f"ssh -F {SSH_CONFIG}",
        "/Users/jon/Developer/preludian/app/",
        "lima-dev-app-a:work/app/",
    ]
    assert "--delete" not in argv
