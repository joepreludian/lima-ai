import re
import shutil
import tempfile
from pathlib import Path

from lima_ai.limactl import Instance
from lima_ai.runner import Runner
from lima_ai.sync import rsync_argv, ssh_host

# Sections of mac GUI diff/merge tools (e.g. Sourcetree) are removed whole.
STRIP_SECTIONS = ("difftool", "mergetool")
# Signing programs installed under these prefixes do not exist in the guest.
HOST_ONLY_PREFIXES = ("/Applications/", "/Library/", "/System/", "/Users/", "/opt/homebrew/", "/usr/local/", "~/")
SIGNING_SWITCHES = ("commit.gpgsign", "tag.gpgsign", "push.gpgsign")
GUEST_EXCLUDESFILE = "~/.config/git/ignore"
# Private keys are recognised by their first line, whatever the file is called.
PRIVATE_KEY_HEADER = re.compile(rb"\A-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


def _entries(runner: Runner, config: Path) -> list[tuple[str, str]]:
    out = runner.run(["git", "config", "-f", config, "--null", "--list"], step="gitconfig").stdout
    entries = []
    for item in out.split("\0"):
        if item:
            key, _, value = item.partition("\n")
            entries.append((key, value))
    return entries


def _strip(runner: Runner, config: Path, home: Path, staging: Path) -> None:
    git = ["git", "config", "-f", str(config)]
    entries = _entries(runner, config)
    keys = {key.lower() for key, _ in entries}

    sections = {key.rsplit(".", 1)[0] for key, _ in entries if key.split(".", 1)[0] in STRIP_SECTIONS}
    for section in sorted(sections):
        runner.run([*git, "--remove-section", section], step="gitconfig")

    helpers = {
        key
        for key, value in entries
        if key.startswith("credential.") and key.endswith(".helper") and "osxkeychain" in value
    }
    for key in sorted(helpers):
        runner.run([*git, "--unset-all", key, "osxkeychain"], step="gitconfig")

    programs = {
        key
        for key, value in entries
        if key.startswith("gpg.") and key.endswith(".program") and value.startswith(HOST_ONLY_PREFIXES)
    }
    for key in sorted(programs):
        runner.run([*git, "--unset-all", key], step="gitconfig")
    if programs:
        for key in SIGNING_SWITCHES:
            if key in keys:
                runner.run([*git, "--unset-all", key], step="gitconfig")

    excludes = [value for key, value in entries if key == "core.excludesfile"]
    if excludes:
        value = excludes[-1]
        source = home / value[2:] if value.startswith("~/") else home / value
        if source.is_file():
            target = staging / ".config/git/ignore"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            runner.run([*git, "core.excludesfile", GUEST_EXCLUDESFILE], step="gitconfig")
        else:
            runner.run([*git, "--unset-all", "core.excludesfile"], step="gitconfig")


def find_private_keys(home: Path) -> list[Path]:
    """Regular files directly in ~/.ssh that start with a PEM private-key header, sorted by name."""
    ssh_dir = home / ".ssh"
    if not ssh_dir.is_dir():
        return []
    keys = []
    for path in sorted(ssh_dir.iterdir()):
        if not path.is_file():
            continue
        with path.open("rb") as f:
            if PRIVATE_KEY_HEADER.match(f.read(64)):
                keys.append(path)
    return keys


def _stage_ssh_file(source: Path, ssh_dir: Path, mode: int) -> None:
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    ssh_dir.chmod(0o700)
    target = ssh_dir / source.name
    shutil.copyfile(source, target)
    target.chmod(mode)


def stage_git_files(runner: Runner, home: Path, staging: Path, ssh_keys: bool = False) -> None:
    """Stage the guest's ~/.gitconfig, ~/.config/git/ignore and ~/.ssh/known_hosts.

    Private keys (and their .pub halves) only when `ssh_keys` is set; ~/.ssh/config never.
    """
    staging.mkdir(parents=True, exist_ok=True)
    source = home / ".gitconfig"
    if source.is_file():
        config = staging / ".gitconfig"
        shutil.copyfile(source, config)
        _strip(runner, config, home, staging)
    ssh_dir = staging / ".ssh"
    known_hosts = home / ".ssh/known_hosts"
    if known_hosts.is_file():
        _stage_ssh_file(known_hosts, ssh_dir, 0o600)
    if ssh_keys:
        for key in find_private_keys(home):
            _stage_ssh_file(key, ssh_dir, 0o600)
            public = key.with_name(key.name + ".pub")
            if public.is_file():
                _stage_ssh_file(public, ssh_dir, 0o644)


def push_git_config(runner: Runner, instance: Instance, host_home: Path, ssh_keys: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="lima-ai-git-") as tmp:
        staging = Path(tmp)
        stage_git_files(runner, host_home, staging, ssh_keys=ssh_keys)
        items = sorted(str(path) for path in staging.iterdir())
        if items:
            # Each item without a trailing slash, so the guest home's own attributes are untouched.
            runner.run(rsync_argv(items, f"{ssh_host(instance.name)}:", instance.ssh_config, []), step="sync-git")
