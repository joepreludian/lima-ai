import pytest

from lima_ai.errors import LimaAiError
from lima_ai.runner import Runner


def test_run_returns_captured_stdout():
    result = Runner().run(["echo", "hello"])
    assert result.returncode == 0
    assert result.stdout == "hello\n"


def test_run_passes_input_over_stdin():
    result = Runner().run(["cat"], input="secret-token")
    assert result.stdout == "secret-token"


def test_nonzero_exit_raises_with_step_and_stderr_tail():
    with pytest.raises(LimaAiError) as excinfo:
        Runner().run(["sh", "-c", "echo boom >&2; exit 3"], step="clone")
    err = excinfo.value
    assert err.step == "clone"
    assert "exit 3" in err.message
    assert err.stderr_tail == "boom"


def test_stderr_tail_keeps_only_last_lines():
    script = "for i in $(seq 1 50); do echo line$i >&2; done; exit 1"
    with pytest.raises(LimaAiError) as excinfo:
        Runner().run(["sh", "-c", script])
    tail = excinfo.value.stderr_tail.splitlines()
    assert tail[-1] == "line50"
    assert len(tail) == 20


def test_step_defaults_to_program_name():
    with pytest.raises(LimaAiError) as excinfo:
        Runner().run(["false"])
    assert excinfo.value.step == "false"


def test_check_false_returns_failed_result():
    result = Runner().run(["sh", "-c", "exit 2"], check=False)
    assert result.returncode == 2


def test_missing_program_raises_clear_error():
    with pytest.raises(LimaAiError) as excinfo:
        Runner().run(["lima-ai-no-such-program"], step="preflight")
    assert "lima-ai-no-such-program" in excinfo.value.message
    assert "not found" in excinfo.value.message


def test_verbose_echoes_command_to_stderr(capsys):
    Runner(verbose=True).run(["echo", "two words"])
    assert "+ echo 'two words'" in capsys.readouterr().err


def test_quiet_runner_does_not_echo(capsys):
    Runner().run(["echo", "x"])
    assert capsys.readouterr().err == ""
