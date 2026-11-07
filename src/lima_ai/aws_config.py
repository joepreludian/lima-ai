"""The host's ~/.aws, copied into a VM.

Copied: `config`, `credentials` and the SSO token cache (`sso/cache/*.json`),
so a profile that uses IAM Identity Center works until the token expires.
Not copied: `cli/cache` (temporary role credentials the CLI derives again).
"""

import shutil
import tempfile
from pathlib import Path

from lima_ai.errors import LimaAiError
from lima_ai.limactl import Instance
from lima_ai.runner import Runner
from lima_ai.sync import rsync_argv, ssh_host

AWS_DIR = ".aws"
PLAIN_FILES = ("config", "credentials")
SSO_CACHE = "sso/cache"


def find_aws_files(home: Path) -> list[Path]:
    """The regular files worth copying from ~/.aws: config, credentials, then the SSO cache by name."""
    aws = home / AWS_DIR
    files = [aws / name for name in PLAIN_FILES if (aws / name).is_file()]
    cache = aws / SSO_CACHE
    if cache.is_dir():
        files += [path for path in sorted(cache.glob("*.json")) if path.is_file()]
    return files


def stage_aws_files(home: Path, staging: Path) -> None:
    """Copy the files into staging/.aws with the same layout; directories 700, files 600."""
    source_root = home / AWS_DIR
    files = find_aws_files(home)
    if files:
        staging.mkdir(parents=True, exist_ok=True)
    for source in files:
        relative = Path(AWS_DIR) / source.relative_to(source_root)
        directory = staging
        for part in relative.parts[:-1]:
            directory = directory / part
            directory.mkdir(mode=0o700, exist_ok=True)
            directory.chmod(0o700)  # mkdir's mode is narrowed by the umask, never widened
        target = staging / relative
        try:
            shutil.copyfile(source, target)
        except OSError as exc:  # e.g. a root-owned token left by a sudo'd aws sso login
            raise LimaAiError("sync-aws", f"cannot read {source}: {exc.strerror}") from None
        target.chmod(0o600)


def push_aws_config(runner: Runner, instance: Instance, host_home: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="lima-ai-aws-") as tmp:
        staging = Path(tmp)
        stage_aws_files(host_home, staging)
        aws = staging / AWS_DIR
        if aws.is_dir():
            # The item without a trailing slash, so the guest home's own attributes are untouched.
            runner.run(rsync_argv([str(aws)], f"{ssh_host(instance.name)}:", instance.ssh_config, []), step="sync-aws")
