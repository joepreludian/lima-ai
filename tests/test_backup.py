import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lima_ai.backup import (
    backup_argv,
    backup_name,
    compose_files,
    detect_compose_files,
    host_commands,
    parse_dotenv,
    resolve_backup,
    restore_argv,
)
from lima_ai.config import Config
from lima_ai.errors import LimaAiError

FIXTURES = Path(__file__).parent / "fixtures"

# --- .env ------------------------------------------------------------------------


def test_dotenv_plain_quoted_export_and_comments():
    text = """
# comment
export COMPOSE_FILE=a.yml:b.yml
SINGLE='x # not a comment'
DOUBLE="y"
INLINE=z # trailing comment
HASH=a#b
  SPACED  =  v
EMPTY=
"""
    assert parse_dotenv(text) == {
        "COMPOSE_FILE": "a.yml:b.yml",
        "SINGLE": "x # not a comment",
        "DOUBLE": "y",
        "INLINE": "z",
        "HASH": "a#b",
        "SPACED": "v",
        "EMPTY": "",
    }


def test_dotenv_ignores_lines_without_equals():
    assert parse_dotenv("garbage\nA=1\n") == {"A": "1"}


# --- compose file detection -------------------------------------------------------


@pytest.mark.parametrize("name", ["compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"])
def test_each_default_name_alone(name):
    assert detect_compose_files({name}, None) == [name]


def test_precedence_when_several_exist():
    assert detect_compose_files({"docker-compose.yaml", "docker-compose.yml", "compose.yml"}, None) == ["compose.yml"]
    assert detect_compose_files({"docker-compose.yaml", "docker-compose.yml"}, None) == ["docker-compose.yml"]
    assert detect_compose_files({"compose.yml", "compose.yaml"}, None) == ["compose.yaml"]


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"compose.override.yml"}, "compose.override.yml"),
        ({"compose.override.yaml"}, "compose.override.yaml"),
        ({"docker-compose.override.yml"}, "docker-compose.override.yml"),
        ({"docker-compose.override.yaml", "compose.override.yaml"}, "compose.override.yaml"),
    ],
)
def test_override_file_is_appended(overrides, expected):
    assert detect_compose_files({"compose.yaml", *overrides}, None) == ["compose.yaml", expected]


def test_override_without_main_file_finds_nothing():
    assert detect_compose_files({"compose.override.yml"}, None) == []


def test_compose_file_from_dotenv_wins():
    files = {"compose.yaml", "compose.override.yml"}
    assert detect_compose_files(files, "COMPOSE_FILE=base.yml:prod.yml\n") == ["base.yml", "prod.yml"]


def test_compose_path_separator_from_dotenv():
    dotenv = "COMPOSE_PATH_SEPARATOR=;\nCOMPOSE_FILE=a.yml;b.yml\n"
    assert detect_compose_files(set(), dotenv) == ["a.yml", "b.yml"]


def test_empty_compose_file_falls_back_to_defaults():
    assert detect_compose_files({"compose.yaml"}, "COMPOSE_FILE=\n") == ["compose.yaml"]


def test_explicit_compose_files_replace_detection():
    assert compose_files(("ops/a.yml", "ops/b.yml"), {"compose.yaml"}, None, required=True, where="x") == [
        "ops/a.yml",
        "ops/b.yml",
    ]


def test_no_compose_file_is_an_error_naming_full_and_compose_file():
    with pytest.raises(LimaAiError) as excinfo:
        compose_files((), {"README.md"}, None, required=True, where="the VM's ~/work/myapp")
    assert "--full" in excinfo.value.message
    assert "--compose-file" in excinfo.value.message
    assert "~/work/myapp" in excinfo.value.message


def test_no_compose_file_is_fine_when_not_required():
    assert compose_files((), set(), None, required=False, where="x") == []


# --- argv -------------------------------------------------------------------------


NOW = datetime(2026, 9, 26, 14, 15, 0, tzinfo=UTC)


def test_backup_name_is_slug_feat_utc_timestamp():
    assert backup_name("myapp", "feat-a", full=False, now=NOW) == "myapp-feat-a-20260926T141500Z"
    assert backup_name("myapp", "feat-a", full=True, now=NOW) == "myapp-feat-a-full-20260926T141500Z"


def test_backup_argv_compose_scoped_joins_files_in_order():
    assert backup_argv(["compose.yaml", "compose.override.yml"], "/backups/docker/n", full=False,
                       no_images=False, no_external=False) == [
        "docker-backup", "backup", "--from-docker-compose", "compose.yaml,compose.override.yml", "/backups/docker/n",
    ]


def test_backup_argv_passes_no_images_and_no_external():
    argv = backup_argv(["compose.yaml"], "/backups/docker/n", full=False, no_images=True, no_external=True)
    assert argv == ["docker-backup", "backup", "--from-docker-compose", "compose.yaml",
                    "--no-images", "--no-external", "/backups/docker/n"]


def test_backup_argv_full_drops_from_docker_compose():
    argv = backup_argv(["compose.yaml"], "/backups/docker/n", full=True, no_images=True, no_external=False)
    assert argv == ["docker-backup", "backup", "--no-images", "/backups/docker/n"]


def test_restore_argv_never_has_yes():
    assert restore_argv(["compose.yaml"], "/backups/docker/n", overwrite=True) == [
        "docker-backup", "restore", "--from-docker-compose", "compose.yaml", "/backups/docker/n", "--overwrite",
    ]
    assert restore_argv([], "/backups/docker/n", overwrite=False) == ["docker-backup", "restore", "/backups/docker/n"]


# --- host commands ---------------------------------------------------------------------


def host_cfg(tmp_path: Path) -> Config:
    return Config(developer_dir=Path.home() / "Developer", backups_dir=Path.home() / "Developer/backups/docker")


def test_host_commands_compose_scoped(tmp_path):
    lines = host_commands(host_cfg(tmp_path), "preludian/myapp", ["compose.yaml", "compose.override.yml"],
                          explicit=False, name="myapp-feat-a-X", full=False, no_external=False)
    text = "\n".join(lines)
    assert "cd ~/Developer/preludian/myapp" in text
    assert "docker compose stop" in text
    assert "docker-backup info ~/Developer/backups/docker/myapp-feat-a-X" in text
    restore = [line for line in lines if "docker-backup restore" in line]
    assert len(restore) == 2
    assert all("--from-docker-compose compose.yaml,compose.override.yml" in line for line in restore)
    assert "--overwrite" not in restore[0] and "new volumes only" in restore[0]
    assert "--overwrite" in restore[1]
    assert "docker compose up -d" in text
    assert "--yes" not in text and " -y" not in text
    assert "external volumes" in text and "--no-external" in text


def test_host_commands_after_no_external_backup_skip_the_external_note(tmp_path):
    text = "\n".join(host_commands(host_cfg(tmp_path), "app", ["compose.yaml"], explicit=False,
                                   name="n", full=False, no_external=True))
    assert "external volumes" not in text


def test_host_commands_with_explicit_files_pass_them_to_compose(tmp_path):
    text = "\n".join(host_commands(host_cfg(tmp_path), "app", ["ops/a.yml", "ops/b.yml"], explicit=True,
                                   name="n", full=False, no_external=False))
    assert "docker compose -f ops/a.yml -f ops/b.yml stop" in text
    assert "docker compose -f ops/a.yml -f ops/b.yml up -d" in text


def test_host_commands_full_print_plain_restore(tmp_path):
    lines = host_commands(host_cfg(tmp_path), "app", ["compose.yaml"], explicit=False, name="n",
                          full=True, no_external=False)
    restore = [line for line in lines if "docker-backup restore" in line]
    assert restore and all("--from-docker-compose" not in line for line in restore)
    text = "\n".join(lines)
    assert "every volume" in text
    assert "--yes" not in text


def test_host_paths_with_spaces_are_quoted(tmp_path):
    cfg = Config(developer_dir=Path.home() / "My Dev", backups_dir=Path.home() / "My Dev/backups")
    text = "\n".join(host_commands(cfg, "my app", ["compose.yaml"], explicit=False, name="n",
                                   full=False, no_external=False))
    assert "cd ~/'My Dev/my app'" in text


# --- backup path -------------------------------------------------------------------


@pytest.fixture
def backups(tmp_path) -> Config:
    cfg = Config(developer_dir=tmp_path, backups_dir=tmp_path / "backups/docker")
    (cfg.backups_dir / "myapp-feat-a-20260926T141500Z").mkdir(parents=True)
    (cfg.backups_dir / "old.tar.bz2").write_text("")
    return cfg


def test_relative_backup_path_is_inside_backups_dir(backups):
    host, guest = resolve_backup(backups, "myapp-feat-a-20260926T141500Z")
    assert host == backups.backups_dir / "myapp-feat-a-20260926T141500Z"
    assert guest == "/backups/docker/myapp-feat-a-20260926T141500Z"


def test_absolute_backup_path_inside_backups_dir(backups):
    host, guest = resolve_backup(backups, str(backups.backups_dir / "old.tar.bz2") + "")
    assert guest == "/backups/docker/old.tar.bz2"


def test_trailing_slash_is_accepted(backups):
    _, guest = resolve_backup(backups, "myapp-feat-a-20260926T141500Z/")
    assert guest == "/backups/docker/myapp-feat-a-20260926T141500Z"


@pytest.mark.parametrize("arg", ["../escape", "/tmp/elsewhere", "a/../../x"])
def test_backup_path_outside_backups_dir_is_rejected(backups, arg):
    with pytest.raises(LimaAiError) as excinfo:
        resolve_backup(backups, arg)
    assert str(backups.backups_dir) in excinfo.value.message


def test_missing_backup_is_rejected(backups):
    with pytest.raises(LimaAiError) as excinfo:
        resolve_backup(backups, "nope")
    assert "not found" in excinfo.value.message


def test_backups_dir_itself_is_not_a_backup(backups):
    with pytest.raises(LimaAiError):
        resolve_backup(backups, str(backups.backups_dir))


def test_backup_name_timestamp_format_is_utc_now():
    assert re.fullmatch(r"a-b-\d{8}T\d{6}Z", backup_name("a", "b", full=False))
