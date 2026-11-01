from pathlib import Path

import pytest

from lima_ai.errors import LimaAiError
from lima_ai.naming import check_project, project_dir, resolve, sanitize

DEV = Path("/Users/jon/Developer")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("myapp", "myapp"),
        ("MyApp", "myapp"),
        ("feat_login", "feat-login"),
        ("My_App.v2", "my-app-v2"),
        ("a__b..c", "a-b-c"),
        ("--x--", "x"),
        ("1", "1"),
        ("ção", "o"),
    ],
)
def test_sanitize(raw, expected):
    assert sanitize(raw) == expected


def test_resolve_builds_every_name():
    names = resolve(DEV, "myapp", "feat-a")
    assert names.project == "myapp"
    assert names.slug == "myapp"
    assert names.workspace == "feat-a"
    assert names.instance == "dev-myapp-feat-a"
    assert names.hostname == "lima-dev-myapp-feat-a"
    assert names.mdns == "lima-dev-myapp-feat-a.local"
    assert names.workdir == "work/myapp"


def test_nested_project_uses_last_component_for_slug():
    names = resolve(DEV, "preludian/riscofauna", "feat_login")
    assert names.project == "preludian/riscofauna"
    assert names.slug == "riscofauna"
    assert names.instance == "dev-riscofauna-feat-login"


def test_trailing_slash_is_ignored():
    assert resolve(DEV, "preludian/riscofauna/", "x").project == "preludian/riscofauna"


def test_absolute_path_inside_developer_dir_is_made_relative():
    assert resolve(DEV, "/Users/jon/Developer/preludian/riscofauna", "x").project == "preludian/riscofauna"


def test_absolute_path_outside_developer_dir_is_rejected():
    with pytest.raises(LimaAiError) as excinfo:
        resolve(DEV, "/tmp/elsewhere", "x")
    assert str(DEV) in excinfo.value.message


@pytest.mark.parametrize("project", ["../escape", "a/../../b", ".", ""])
def test_project_must_stay_inside_developer_dir(project):
    with pytest.raises(LimaAiError):
        resolve(DEV, project, "x")


@pytest.mark.parametrize("project, workspace", [("___", "x"), ("app", "__"), ("app", "")])
def test_empty_slug_or_workspace_after_sanitising_is_an_error(project, workspace):
    with pytest.raises(LimaAiError, match="sanitised"):
        resolve(DEV, project, workspace)


def test_hostname_over_63_chars_is_an_error_naming_it():
    workspace = "f" * 50
    with pytest.raises(LimaAiError) as info:
        resolve(DEV, "myapp", workspace)
    hostname = f"lima-dev-myapp-{workspace}"
    assert hostname in info.value.message
    assert str(len(hostname)) in info.value.message
    assert "shorter workspace name" in info.value.message


def test_hostname_of_exactly_63_chars_is_allowed():
    workspace = "f" * (63 - len("lima-dev-myapp-"))
    assert len(resolve(DEV, "myapp", workspace).hostname) == 63


def test_names_never_collide_with_reserved_base():
    assert resolve(DEV, "base", "x").instance != "dev-base"


def test_project_dir_requires_existing_directory(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "file").write_text("")
    assert project_dir(tmp_path, resolve(tmp_path, "app", "x")) == tmp_path / "app"
    with pytest.raises(LimaAiError):
        project_dir(tmp_path, resolve(tmp_path, "missing", "x"))
    with pytest.raises(LimaAiError):
        project_dir(tmp_path, resolve(tmp_path, "file", "x"))


def test_check_project_returns_the_path_relative_to_developer_dir(tmp_path):
    (tmp_path / "preludian/myapp").mkdir(parents=True)
    assert check_project(tmp_path, "preludian/myapp") == "preludian/myapp"
    assert check_project(tmp_path, "preludian/myapp/") == "preludian/myapp"
    assert check_project(tmp_path, str(tmp_path / "preludian/myapp")) == "preludian/myapp"


def test_check_project_rejects_a_missing_folder(tmp_path):
    with pytest.raises(LimaAiError, match="does not exist"):
        check_project(tmp_path, "preludian/nope")


def test_check_project_rejects_a_folder_outside_developer_dir(tmp_path):
    with pytest.raises(LimaAiError, match="inside"):
        check_project(tmp_path, "/etc")
