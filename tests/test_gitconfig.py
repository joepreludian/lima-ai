import shutil
import subprocess
from pathlib import Path

import pytest

from lima_ai.gitconfig import stage_git_files
from lima_ai.runner import Runner

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git_get(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "config", "-f", str(path), *args], capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def home(tmp_path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    shutil.copy(FIXTURES / "gitconfig", home / ".gitconfig")
    (home / ".gitignore_global").write_text(".DS_Store\n*.swp\n")
    (home / ".ssh").mkdir()
    (home / ".ssh/known_hosts").write_text("github.com ssh-ed25519 AAAA\n")
    (home / ".ssh/id_ed25519").write_text("PRIVATE KEY")
    return home


def test_strips_difftool_mergetool_and_keychain_helper(home, tmp_path):
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    config = staging / ".gitconfig"
    assert git_get(config, "--get-regexp", r"^(difftool|mergetool)\.") == ""
    assert git_get(config, "--get-all", "credential.helper") == ""
    assert git_get(config, "--get", "credential.https://example.com.helper") == "store"


def test_keeps_identity_aliases_and_other_settings(home, tmp_path):
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    config = staging / ".gitconfig"
    assert git_get(config, "--get", "user.name") == "Jon Trigueiro"
    assert git_get(config, "--get", "user.email") == "jon@example.com"
    assert git_get(config, "--get", "alias.st") == "status -sb"
    assert git_get(config, "--get", "pull.rebase") == "true"
    assert git_get(config, "--get", "core.autocrlf") == "input"


def test_excludesfile_is_copied_and_key_rewritten(home, tmp_path):
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    assert git_get(staging / ".gitconfig", "--get", "core.excludesfile") == "~/.config/git/ignore"
    assert (staging / ".config/git/ignore").read_text() == ".DS_Store\n*.swp\n"


def test_missing_excludesfile_is_unset(home, tmp_path):
    (home / ".gitignore_global").unlink()
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    assert git_get(staging / ".gitconfig", "--get", "core.excludesfile") == ""
    assert not (staging / ".config").exists()


def test_known_hosts_copied_private_keys_never(home, tmp_path):
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    known_hosts = staging / ".ssh/known_hosts"
    assert known_hosts.read_text() == "github.com ssh-ed25519 AAAA\n"
    assert known_hosts.stat().st_mode & 0o777 == 0o600
    assert (staging / ".ssh").stat().st_mode & 0o777 == 0o700
    assert sorted(p.name for p in (staging / ".ssh").iterdir()) == ["known_hosts"]


def test_host_only_signing_program_is_stripped_with_signing(home, tmp_path):
    with (home / ".gitconfig").open("a") as f:
        f.write('[gpg]\n\tformat = ssh\n[gpg "ssh"]\n\tprogram = /Applications/1Password.app/Contents/MacOS/op-ssh-sign\n')
        f.write("[commit]\n\tgpgsign = true\n[tag]\n\tgpgsign = true\n")
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    config = staging / ".gitconfig"
    assert git_get(config, "--get", "gpg.ssh.program") == ""
    assert git_get(config, "--get", "commit.gpgsign") == ""
    assert git_get(config, "--get", "tag.gpgsign") == ""
    assert git_get(config, "--get", "gpg.format") == "ssh"


def test_portable_signing_program_is_kept(home, tmp_path):
    with (home / ".gitconfig").open("a") as f:
        f.write("[gpg]\n\tprogram = gpg\n[commit]\n\tgpgsign = true\n")
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    assert git_get(staging / ".gitconfig", "--get", "gpg.program") == "gpg"
    assert git_get(staging / ".gitconfig", "--get", "commit.gpgsign") == "true"


def test_host_gitconfig_is_not_modified(home, tmp_path):
    before = (home / ".gitconfig").read_text()
    stage_git_files(Runner(), home, tmp_path / "staging")
    assert (home / ".gitconfig").read_text() == before


def test_no_gitconfig_and_no_known_hosts_stage_nothing(tmp_path):
    home = tmp_path / "empty-home"
    home.mkdir()
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging)
    assert not any(staging.rglob("*"))
