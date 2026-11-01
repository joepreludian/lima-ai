import shutil
import subprocess
from pathlib import Path

import pytest

from lima_ai.gitconfig import find_private_keys, stage_git_files
from lima_ai.runner import Runner

FIXTURES = Path(__file__).parent / "fixtures"
OPENSSH_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----\n"
RSA_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----\n"

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
    (home / ".ssh/id_ed25519").write_text(OPENSSH_KEY)
    (home / ".ssh/id_ed25519.pub").write_text("ssh-ed25519 AAAA jon@mac\n")
    (home / ".ssh/work.key").write_text(RSA_KEY)
    (home / ".ssh/config").write_text("Host github.com\n    IdentityFile ~/.ssh/work.key\n")
    (home / ".ssh/notes.txt").write_text("not a key\n")
    (home / ".ssh/agent").mkdir()
    (home / ".ssh/agent/socket.key").write_text(OPENSSH_KEY)
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


def test_find_private_keys_goes_by_header_not_name(home):
    assert [p.name for p in find_private_keys(home)] == ["id_ed25519", "work.key"]


def test_find_private_keys_without_ssh_dir(tmp_path):
    assert find_private_keys(tmp_path) == []


def test_private_keys_staged_on_request_with_their_public_halves(home, tmp_path):
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging, ssh_keys=True)
    ssh = staging / ".ssh"
    assert sorted(p.name for p in ssh.iterdir()) == ["id_ed25519", "id_ed25519.pub", "known_hosts", "work.key"]
    assert (ssh / "id_ed25519").read_text() == OPENSSH_KEY
    assert (ssh / "id_ed25519").stat().st_mode & 0o777 == 0o600
    assert (ssh / "work.key").stat().st_mode & 0o777 == 0o600
    assert (ssh / "id_ed25519.pub").stat().st_mode & 0o777 == 0o644
    assert ssh.stat().st_mode & 0o777 == 0o700


def test_private_keys_staged_even_without_known_hosts(home, tmp_path):
    (home / ".ssh/known_hosts").unlink()
    staging = tmp_path / "staging"
    stage_git_files(Runner(), home, staging, ssh_keys=True)
    ssh = staging / ".ssh"
    assert sorted(p.name for p in ssh.iterdir()) == ["id_ed25519", "id_ed25519.pub", "work.key"]
    assert ssh.stat().st_mode & 0o777 == 0o700


def test_host_only_signing_program_is_stripped_with_signing(home, tmp_path):
    with (home / ".gitconfig").open("a") as f:
        f.write(
            '[gpg]\n\tformat = ssh\n[gpg "ssh"]\n\tprogram = /Applications/1Password.app/Contents/MacOS/op-ssh-sign\n'
        )
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
