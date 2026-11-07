import os
from pathlib import Path

import pytest

from lima_ai.aws_config import find_aws_files, push_aws_config, stage_aws_files
from lima_ai.errors import LimaAiError
from lima_ai.limactl import Instance
from tests.fakes import FakeRunner

INSTANCE = Instance(
    name="dev-myapp-feat-a",
    status="Running",
    dir=Path("/Users/jon/.lima/dev-myapp-feat-a"),
    ssh_config=Path("/Users/jon/.lima/dev-myapp-feat-a/ssh.config"),
)


@pytest.fixture
def home(tmp_path) -> Path:
    home = tmp_path / "home"
    aws = home / ".aws"
    (aws / "sso/cache").mkdir(parents=True)
    (aws / "cli/cache").mkdir(parents=True)
    (aws / "config").write_text("[profile dev]\nsso_session = acme\n")
    (aws / "config").chmod(0o644)
    (aws / "credentials").write_text("[default]\naws_access_key_id = AKIA\n")
    (aws / "sso/cache/b1.json").write_text('{"accessToken": "t"}\n')
    (aws / "sso/cache/a2.json").write_text('{"accessToken": "u"}\n')
    (aws / "sso/cache/notes.txt").write_text("not a token\n")
    (aws / "sso/cache/sub").mkdir()
    (aws / "sso/cache/sub/c3.json").write_text("{}\n")
    (aws / "cli/cache/role.json").write_text("{}\n")
    return home


def test_find_lists_config_credentials_then_sorted_sso_cache_json(home):
    aws = home / ".aws"
    assert find_aws_files(home) == [
        aws / "config",
        aws / "credentials",
        aws / "sso/cache/a2.json",
        aws / "sso/cache/b1.json",
    ]


def test_find_is_empty_without_aws_dir(tmp_path):
    assert find_aws_files(tmp_path / "home") == []


def test_find_is_empty_when_only_cli_cache_exists(tmp_path):
    home = tmp_path / "home"
    (home / ".aws/cli/cache").mkdir(parents=True)
    (home / ".aws/cli/cache/role.json").write_text("{}\n")
    assert find_aws_files(home) == []


def test_find_follows_a_symlinked_config(tmp_path):
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    target = tmp_path / "dotfiles/aws-config"
    target.parent.mkdir()
    target.write_text("[default]\nregion = eu-west-1\n")
    (home / ".aws/config").symlink_to(target)
    assert find_aws_files(home) == [home / ".aws/config"]


def test_stage_copies_the_layout_with_tight_modes(home, tmp_path):
    staging = tmp_path / "staging"
    stage_aws_files(home, staging)
    aws = staging / ".aws"
    assert sorted(p.relative_to(aws).as_posix() for p in aws.rglob("*") if p.is_file()) == [
        "config",
        "credentials",
        "sso/cache/a2.json",
        "sso/cache/b1.json",
    ]
    assert (aws / "config").read_text() == "[profile dev]\nsso_session = acme\n"
    for directory in (aws, aws / "sso", aws / "sso/cache"):
        assert directory.stat().st_mode & 0o777 == 0o700
    for file in aws.rglob("*"):
        if file.is_file():
            assert file.stat().st_mode & 0o777 == 0o600
    assert not (aws / "cli").exists()


def test_stage_turns_a_symlinked_config_into_a_regular_file(tmp_path):
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    target = tmp_path / "aws-config"
    target.write_text("[default]\nregion = eu-west-1\n")
    (home / ".aws/config").symlink_to(target)
    stage_aws_files(home, tmp_path / "staging")
    staged = tmp_path / "staging/.aws/config"
    assert not staged.is_symlink()
    assert staged.read_text() == "[default]\nregion = eu-west-1\n"


def test_stage_creates_nothing_when_there_is_nothing_to_copy(tmp_path):
    stage_aws_files(tmp_path / "home", tmp_path / "staging")
    assert not (tmp_path / "staging").exists()


def test_push_rsyncs_the_aws_dir_to_the_guest_home_without_delete(home):
    runner = FakeRunner()
    push_aws_config(runner, INSTANCE, home)
    assert len(runner.calls) == 1
    argv = runner.calls[0].argv
    assert argv[:2] == ["rsync", "-a"]
    assert "--delete" not in argv
    assert argv[-3] == "ssh -F /Users/jon/.lima/dev-myapp-feat-a/ssh.config"
    assert argv[-2].endswith("/.aws") and "lima-ai-aws-" in argv[-2]
    assert argv[-1] == "lima-dev-myapp-feat-a:"


def test_push_does_nothing_without_aws_files(tmp_path):
    runner = FakeRunner()
    push_aws_config(runner, INSTANCE, tmp_path / "home")
    assert runner.calls == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_stage_reports_an_unreadable_file_as_a_lima_ai_error(home, tmp_path):
    token = home / ".aws/sso/cache/a2.json"
    token.chmod(0o000)
    try:
        with pytest.raises(LimaAiError) as info:
            stage_aws_files(home, tmp_path / "staging")
    finally:
        token.chmod(0o600)
    assert info.value.step == "sync-aws"
    assert str(token) in info.value.message
