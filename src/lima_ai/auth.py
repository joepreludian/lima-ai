import os

from lima_ai.config import config_dir
from lima_ai.errors import LimaAiError
from lima_ai.runner import Runner


def token_path():
    return config_dir() / "oauth-token"


def read_token() -> str:
    path = token_path()
    if not path.is_file():
        raise LimaAiError("auth", f"no Claude token at {path}; run `lima-ai auth` first")
    return path.read_text().strip()


def write_token(token: str) -> None:
    token = token.strip()
    if not token or any(char.isspace() for char in token):
        raise LimaAiError("auth", "the token must be a single non-empty word")
    path = token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    path.chmod(0o600)


def run_setup_token(runner: Runner) -> None:
    """`claude setup-token` prints a long-lived OAuth token for the Max subscription."""
    runner.run(["claude", "setup-token"], interactive=True, step="auth")
