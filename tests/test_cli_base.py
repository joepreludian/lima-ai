import dataclasses

import pytest

from lima_ai.config import BaseConfig
from tests.fakes import lima_list


def test_init_hook_writes_the_starter_and_prints_the_next_step(env):
    target = env.tmp_path / "hooks/custom.sh"
    result = env.invoke(["base", "--init-hook", str(target)])
    assert result.exit_code == 0, result.output
    assert target.is_file()
    assert f"Wrote {target}. Edit it, then build with:" in result.output
    assert f"lima-ai base --use-hook {target} --rebuild" in result.output
    assert not env.runner.calls
    assert not (env.tmp_path / "config/lima-ai/config.toml").exists()


def test_init_hook_does_not_need_limactl(env, monkeypatch):
    monkeypatch.setenv("PATH", str(env.tmp_path))
    result = env.invoke(["base", "--init-hook", str(env.tmp_path / "h.sh")])
    assert result.exit_code == 0, result.output


def test_init_hook_refuses_an_existing_file(env):
    target = env.tmp_path / "h.sh"
    target.write_text("mine\n")
    result = env.invoke(["base", "--init-hook", str(target)])
    assert result.exit_code == 1
    assert "error [base]:" in result.output and "exists" in result.output
    assert target.read_text() == "mine\n"


@pytest.mark.parametrize("extra", [["--use-hook", "x.sh"], ["--rebuild"]])
def test_init_hook_cannot_be_combined(env, extra):
    result = env.invoke(["base", "--init-hook", "h.sh", *extra])
    assert result.exit_code == 2
    assert "--init-hook cannot be combined with --use-hook or --rebuild" in result.output


def test_use_hook_saves_the_absolute_path_and_builds_with_it(env, monkeypatch):
    monkeypatch.chdir(env.tmp_path)
    (env.tmp_path / "custom.sh").write_text("echo java\n")
    result = env.invoke(["base", "--use-hook", "custom.sh"])
    assert result.exit_code == 0, result.output
    config = (env.tmp_path / "config/lima-ai/config.toml").read_text()
    assert config == f'[base]\nhook = "{env.tmp_path / "custom.sh"}"\n'
    hook_call = next(c for c in env.runner.calls if "echo java\n" in c.argv)
    assert hook_call.argv[-3:] == ["bash", "-c", "echo java\n"]


def test_missing_use_hook_saves_nothing_and_runs_nothing(env):
    result = env.invoke(["base", "--use-hook", str(env.tmp_path / "nope.sh")])
    assert result.exit_code == 1
    assert "error [base]: hook" in result.output and "not found" in result.output
    assert not env.runner.calls
    assert not (env.tmp_path / "config/lima-ai/config.toml").exists()


def test_use_hook_is_saved_even_when_rebuild_is_missing(env):
    (env.tmp_path / "h.sh").write_text("true\n")
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped")))
    result = env.invoke(["base", "--use-hook", str(env.tmp_path / "h.sh")])
    assert result.exit_code == 1
    assert "use --rebuild" in result.output and "hook saved" in result.output
    assert f'hook = "{env.tmp_path / "h.sh"}"' in (env.tmp_path / "config/lima-ai/config.toml").read_text()


def test_saved_hook_is_used_without_the_flag(env):
    (env.tmp_path / "h.sh").write_text("echo saved\n")
    env.cfg = dataclasses.replace(env.cfg, base=BaseConfig(hook=env.tmp_path / "h.sh"))
    result = env.invoke(["base"])
    assert result.exit_code == 0, result.output
    assert any("echo saved\n" in c.argv for c in env.runner.calls)
    assert "(from config.toml)" in result.output
