import os

import click
import pytest

from lima_ai.config import Config
from lima_ai.errors import LimaAiError
from lima_ai.picker import candidates, pick_with_fzf
from tests.fakes import FakeRunner

FZF_ARGV = ["fzf", "--prompt", "Project> ", "--height", "40%", "--reverse", "--no-multi"]


def tree(root, *paths):
    for path in paths:
        (root / path).mkdir(parents=True, exist_ok=True)


def test_candidates_lists_folders_up_to_three_levels_marking_git_repos(tmp_path):
    dev = tmp_path / "Developer"
    tree(dev, "clients/acme/api/.git", "clients/acme/api/src/deep", "opensource/lima_ai/.git", "resume", "a/b/c/d")
    (dev / "notes.txt").write_text("")
    cfg = Config(developer_dir=dev, backups_dir=tmp_path / "elsewhere")
    assert candidates(cfg) == [
        ("a", False),
        ("a/b", False),
        ("a/b/c", False),
        ("clients", False),
        ("clients/acme", False),
        ("clients/acme/api", True),
        ("opensource", False),
        ("opensource/lima_ai", True),
        ("resume", False),
    ]


def test_candidates_skip_hidden_excluded_and_backup_folders(tmp_path):
    dev = tmp_path / "Developer"
    tree(dev, ".hidden/x", "node_modules/pkg", "app/.venv", "app/src", "backups/docker/myapp-feat-a-X", "app/.git")
    cfg = Config(developer_dir=dev, backups_dir=dev / "backups/docker")
    assert candidates(cfg) == [("app", True), ("backups", False)]


def test_candidates_do_not_descend_into_a_repository(tmp_path):
    dev = tmp_path / "Developer"
    tree(dev, "repo/.git", "repo/packages/web")
    cfg = Config(developer_dir=dev, backups_dir=tmp_path / "b")
    assert candidates(cfg) == [("repo", True)]


def test_candidates_offer_a_symlinked_project_without_descending_into_it(tmp_path):
    dev = tmp_path / "Developer"
    tree(dev, "preludian", tmp_path / "elsewhere/linked/.git", tmp_path / "elsewhere/linked/packages/web")
    (dev / "preludian/linked").symlink_to(tmp_path / "elsewhere/linked")
    (dev / "preludian/broken").symlink_to(tmp_path / "gone")
    cfg = Config(developer_dir=dev, backups_dir=tmp_path / "b")
    assert candidates(cfg) == [("preludian", False), ("preludian/linked", True)]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read every folder")
def test_candidates_skip_an_unreadable_folder(tmp_path):
    dev = tmp_path / "Developer"
    tree(dev, "locked/secret", "open/app/.git")
    (dev / "locked").chmod(0o000)
    try:
        cfg = Config(developer_dir=dev, backups_dir=tmp_path / "b")
        assert candidates(cfg) == [("locked", False), ("open", False), ("open/app", True)]
    finally:
        (dev / "locked").chmod(0o755)


def test_candidates_fail_clearly_when_developer_dir_is_missing(tmp_path):
    cfg = Config(developer_dir=tmp_path / "nope", backups_dir=tmp_path / "b")
    with pytest.raises(LimaAiError, match="does not exist"):
        candidates(cfg)


def test_candidates_fail_clearly_when_there_is_nothing_to_pick(tmp_path):
    dev = tmp_path / "Developer"
    dev.mkdir()
    cfg = Config(developer_dir=dev, backups_dir=tmp_path / "b")
    with pytest.raises(LimaAiError, match="no project folders"):
        candidates(cfg)


def developer(tmp_path):
    dev = tmp_path / "Developer"
    tree(dev, "opensource/other", "preludian/myapp/.git")
    return Config(developer_dir=dev, backups_dir=dev / "backups/docker")


def test_pick_with_fzf_feeds_the_candidates_and_returns_the_choice_without_the_marker(tmp_path):
    cfg = developer(tmp_path)
    runner = FakeRunner()
    runner.on("fzf --prompt", "preludian/myapp  (git)\n")
    assert pick_with_fzf(cfg, runner) == "preludian/myapp"
    fzf = runner.find("fzf --prompt")
    assert len(fzf) == 1
    assert fzf[0].argv == FZF_ARGV
    assert fzf[0].input == "opensource\nopensource/other\npreludian\npreludian/myapp  (git)\n"


def test_pick_with_fzf_aborts_when_cancelled(tmp_path):
    cfg = developer(tmp_path)
    runner = FakeRunner()
    runner.on("fzf --prompt", returncode=130)
    with pytest.raises(click.Abort):
        pick_with_fzf(cfg, runner)
