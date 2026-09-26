class LimaAiError(Exception):
    """A failure the CLI reports as `error [<step>]: <message>` and exit 1."""

    def __init__(self, step: str, message: str, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.step = step
        self.message = message
        self.stderr_tail = stderr_tail
