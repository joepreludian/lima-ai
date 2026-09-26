import re
from pathlib import Path

from tests.conftest import GUEST_HOME
from tests.fakes import lima_list

INSTANCE = "dev-myapp-feat-a"
WORKDIR = f"{GUEST_HOME}/work/myapp"
IN_VM = f"limactl shell --workdir {WORKDIR} {INSTANCE}"
FIXTURES = Path(__file__).parent / "fixtures"


def running_vm(env, files="compose.yaml\ncompose.override.yml\nsrc\n"):
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped"), (INSTANCE, "Running")))
    env.runner.on(f"{IN_VM} ls -1A", files)


def docker_commands(env) -> list[str]:
    """Commands run in the working copy, minus the listing reads (ls -1A, cat .env)."""
    listing = (f"{IN_VM} ls -1A", f"{IN_VM} cat .env")
    return [c.removeprefix(IN_VM + " ") for c in env.runner.commands if c.startswith(IN_VM) and c not in listing]


# --- backup -------------------------------------------------------------------------


def test_backup_stops_backs_up_starts_and_shows_info(env):
    running_vm(env)
    result = env.invoke(["backup", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    cmds = docker_commands(env)
    assert cmds[0] == "docker compose -f compose.yaml -f compose.override.yml stop"
    assert re.fullmatch(
        r"docker-backup backup --from-docker-compose compose.yaml,compose.override.yml "
        r"/backups/docker/myapp-feat-a-\d{8}T\d{6}Z",
        cmds[1],
    )
    assert cmds[2] == "docker compose -f compose.yaml -f compose.override.yml start"
    assert re.fullmatch(r"docker-backup info /backups/docker/myapp-feat-a-\d{8}T\d{6}Z", cmds[3])
    assert env.runner.find("docker-backup backup")[0].interactive
    assert str(env.cfg.backups_dir / "myapp-feat-a-") in result.output


def test_backup_starts_compose_again_when_docker_backup_fails(env):
    running_vm(env)
    env.runner.on("docker-backup backup", returncode=2)
    result = env.invoke(["backup", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    cmds = docker_commands(env)
    assert cmds[-1] == "docker compose -f compose.yaml -f compose.override.yml start"
    assert not any("docker-backup info" in c for c in cmds)


def test_backup_prints_host_commands_from_host_project_files(env):
    running_vm(env)
    (env.cfg.developer_dir / "preludian/myapp/docker-compose.yml").write_text("services: {}\n")
    result = env.invoke(["backup", "preludian/myapp", "feat-a"])
    assert "docker-backup restore --from-docker-compose docker-compose.yml " in result.output
    assert "--yes" not in result.output


def test_backup_without_compose_file_fails_and_suggests_full(env):
    running_vm(env, files="README.md\n")
    result = env.invoke(["backup", "preludian/myapp", "feat-a"])
    assert result.exit_code == 1
    assert "--full" in result.output
    assert not env.runner.find("docker-backup backup")


def test_backup_full_without_compose_file_skips_compose_stop(env):
    running_vm(env, files="README.md\n")
    result = env.invoke(["backup", "preludian/myapp", "feat-a", "--full"])
    assert result.exit_code == 0, result.output
    cmds = docker_commands(env)
    assert not any(c.startswith("docker compose") for c in cmds)
    assert re.fullmatch(r"docker-backup backup /backups/docker/myapp-feat-a-full-\d{8}T\d{6}Z", cmds[0])
    assert "no compose file" in result.output


def test_backup_full_rejects_no_external_and_compose_file(env):
    running_vm(env)
    assert env.invoke(["backup", "preludian/myapp", "feat-a", "--full", "--no-external"]).exit_code == 1
    assert env.invoke(["backup", "preludian/myapp", "feat-a", "--full", "--compose-file", "x.yml"]).exit_code == 1
    assert not env.runner.find("docker-backup")


def test_backup_with_explicit_compose_files(env):
    running_vm(env)
    result = env.invoke(
        [
            "backup",
            "preludian/myapp",
            "feat-a",
            "--compose-file",
            "ops/a.yml",
            "--compose-file",
            "ops/b.yml",
            "--no-images",
        ]
    )
    assert result.exit_code == 0, result.output
    cmds = docker_commands(env)
    assert cmds[0] == "docker compose -f ops/a.yml -f ops/b.yml stop"
    assert cmds[1].startswith("docker-backup backup --from-docker-compose ops/a.yml,ops/b.yml --no-images ")


def test_backup_reads_compose_file_from_guest_dotenv(env):
    running_vm(env, files="compose.yaml\n.env\n")
    env.runner.on(f"{IN_VM} cat .env", "COMPOSE_FILE=compose.yaml:compose.dev.yaml\n")
    env.invoke(["backup", "preludian/myapp", "feat-a"])
    assert docker_commands(env)[1].startswith(
        "docker-backup backup --from-docker-compose compose.yaml,compose.dev.yaml "
    )


# --- restore ------------------------------------------------------------------------


def make_backup(env, name="myapp-feat-a-20260926T141500Z", info="info-backup.json"):
    (env.cfg.backups_dir / name).mkdir(parents=True)
    env.runner.on("docker-backup info --json", (FIXTURES / info).read_text())
    return name


def test_restore_runs_docker_backup_attached_without_yes_then_up(env):
    running_vm(env)
    name = make_backup(env)
    result = env.invoke(["restore", "preludian/myapp", "feat-a", name])
    assert result.exit_code == 0, result.output
    cmds = docker_commands(env)
    assert cmds == [
        f"docker-backup info --json /backups/docker/{name}",
        f"docker-backup info /backups/docker/{name}",
        "docker compose -f compose.yaml -f compose.override.yml stop",
        f"docker-backup restore --from-docker-compose compose.yaml,compose.override.yml /backups/docker/{name}",
        "docker compose -f compose.yaml -f compose.override.yml up -d",
    ]
    restore = env.runner.find("docker-backup restore")[0]
    assert restore.interactive
    assert "--yes" not in restore.argv and "-y" not in restore.argv
    assert "was not created by Docker Compose" in result.output


def test_restore_refuses_single_volume_archive_with_hint(env):
    running_vm(env)
    name = make_backup(env, name="pgdata-20260926T141500Z.tar.bz2", info="info-volume.json")
    result = env.invoke(["restore", "preludian/myapp", "feat-a", name])
    assert result.exit_code == 1
    assert "restore-volume" in result.output
    assert "lima-ai shell preludian/myapp feat-a" in result.output
    assert not env.runner.find("docker-backup restore")
    assert not env.runner.find("docker compose")


def test_restore_overwrite_asks_before_docker_backup_runs(env):
    running_vm(env)
    name = make_backup(env)
    result = env.invoke(["restore", "preludian/myapp", "feat-a", name, "--overwrite"], input="n\n")
    assert result.exit_code == 1
    assert "external" in result.output
    assert not env.runner.find("docker-backup restore")
    assert not env.runner.find("docker compose")
    result = env.invoke(["restore", "preludian/myapp", "feat-a", name, "--overwrite"], input="y\n")
    assert result.exit_code == 0
    assert env.runner.find("docker-backup restore")[-1].argv[-1] == "--overwrite"


def test_restore_declined_or_nothing_to_restore_starts_stack_again(env):
    for code in (2, 3):
        running_vm(env)
        name = make_backup(env, name=f"b{code}")
        env.runner.on("docker-backup restore", returncode=code)
        result = env.invoke(["restore", "preludian/myapp", "feat-a", name])
        assert result.exit_code == 1
        assert docker_commands(env)[-1] == "docker compose -f compose.yaml -f compose.override.yml start"
        assert "nothing was changed" in result.output


def test_restore_partial_failure_leaves_stack_stopped(env):
    running_vm(env)
    name = make_backup(env)
    env.runner.on("docker-backup restore", returncode=1)
    result = env.invoke(["restore", "preludian/myapp", "feat-a", name])
    assert result.exit_code == 1
    cmds = docker_commands(env)
    assert cmds[-1].startswith("docker-backup restore")
    assert "--overwrite" in result.output
    assert "stopped" in result.output


def test_restore_full_leaves_out_from_docker_compose(env):
    running_vm(env)
    name = make_backup(env)
    env.invoke(["restore", "preludian/myapp", "feat-a", name, "--full"])
    assert env.runner.find("docker-backup restore")[0].argv == [
        "limactl",
        "shell",
        "--workdir",
        WORKDIR,
        INSTANCE,
        "docker-backup",
        "restore",
        f"/backups/docker/{name}",
    ]


def test_restore_without_compose_file_restores_everything_and_skips_compose(env):
    running_vm(env, files="README.md\n")
    name = make_backup(env)
    result = env.invoke(["restore", "preludian/myapp", "feat-a", name])
    assert result.exit_code == 0, result.output
    cmds = docker_commands(env)
    assert f"docker-backup restore /backups/docker/{name}" in cmds
    assert not any(c.startswith("docker compose") for c in cmds)


def test_restore_rejects_paths_outside_backups_dir(env):
    running_vm(env)
    result = env.invoke(["restore", "preludian/myapp", "feat-a", "/etc"])
    assert result.exit_code == 1
    assert not env.runner.find("docker-backup")


# --- new --restore --------------------------------------------------------------------


def test_new_with_restore_restores_after_project_without_overwrite(env):
    from lima_ai.auth import write_token

    write_token("tok")
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped"), (INSTANCE, "Running")))
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped")), times=1)
    env.runner.on(f"{IN_VM} ls -1A", "compose.yaml\n")
    name = make_backup(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--restore", name])
    assert result.exit_code == 0, result.output
    cmds = env.runner.commands
    project = next(i for i, c in enumerate(cmds) if "--exclude-from=" in c)
    restore = next(i for i, c in enumerate(cmds) if "docker-backup restore" in c)
    assert project < restore
    assert "--overwrite" not in cmds[restore]


def test_new_with_bad_restore_path_fails_before_cloning(env):
    from lima_ai.auth import write_token

    write_token("tok")
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped")))
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--restore", "missing"])
    assert result.exit_code == 1
    assert not env.runner.find("limactl clone")
