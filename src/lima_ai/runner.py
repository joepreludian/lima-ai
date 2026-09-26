import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from lima_ai.errors import LimaAiError

STDERR_TAIL_LINES = 20


class Runner:
    """Runs every subprocess lima-ai starts, so errors and echo behave the same."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def run(
        self,
        argv: Sequence[str],
        input: str | None = None,
        check: bool = True,
        interactive: bool = False,
        step: str | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess:
        """Run argv; interactive commands inherit the terminal instead of being captured.

        `input` goes over stdin, never argv, so secrets passed that way are
        safe to echo in verbose mode.
        """
        argv = [str(arg) for arg in argv]
        step = step or Path(argv[0]).name
        if self.verbose:
            print(f"+ {shlex.join(argv)}", file=sys.stderr)
        try:
            if interactive:
                result = subprocess.run(argv, cwd=cwd, text=True)
            else:
                result = subprocess.run(argv, input=input, cwd=cwd, capture_output=True, text=True)
        except FileNotFoundError:
            raise LimaAiError(step, f"{argv[0]} not found on PATH") from None
        if check and result.returncode != 0:
            raise_for_exit(step, argv, result.returncode, result.stderr or "")
        return result


def raise_for_exit(step: str, argv: Sequence[str], returncode: int, stderr: str) -> None:
    tail = "\n".join(stderr.strip().splitlines()[-STDERR_TAIL_LINES:])
    raise LimaAiError(step, f"`{shlex.join(argv)}` failed (exit {returncode})", tail)
