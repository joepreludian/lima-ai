"""`lima-ai new` filling in what the command line left out."""

import shutil

from tests.test_instance import INSTANCE, WORKDIR, base_then_clone

# Interactive runs end with the shell offer (Task 8); "n" answers it. Extra
# input is ignored by CliRunner until that offer exists.
NO_SHELL = "n\n"


def ready(env):
    env.write_token()
    base_then_clone(env)


def switch_commands(env):
    return [c for c in env.runner.commands if f"git -C {WORKDIR} switch" in c]


def test_new_without_arguments_outside_a_terminal_is_a_usage_error(env):
    ready(env)
    result = env.invoke(["new"])
    assert result.exit_code == 1
    assert "error [usage]: PROJECT and WORKSPACE are required outside a terminal" in result.output
    assert not env.runner.find("limactl clone")


def test_new_with_project_only_outside_a_terminal_is_a_usage_error(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp"])
    assert result.exit_code == 1
    assert "error [usage]" in result.output


def test_new_rejects_branch_and_no_branch_together(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--branch", "x", "--no-branch"])
    assert result.exit_code == 1
    assert "--branch and --no-branch cannot be combined" in result.output
    assert not env.runner.find("limactl clone")


def test_new_defaults_the_branch_to_the_workspace_outside_a_terminal(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert result.exit_code == 0, result.output
    assert switch_commands(env) == [f"limactl shell {INSTANCE} git -C {WORKDIR} switch -c feat-a"]


def test_new_branch_flag_overrides_the_default(env):
    ready(env)
    env.invoke(["new", "preludian/myapp", "feat-a", "--branch", "feat/login"])
    assert switch_commands(env) == [f"limactl shell {INSTANCE} git -C {WORKDIR} switch -c feat/login"]


def test_new_no_branch_skips_the_branch_step(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--no-branch"])
    assert result.exit_code == 0, result.output
    assert switch_commands(env) == []


def test_new_warns_when_the_project_has_no_git_and_runs_no_git_command(env):
    ready(env)
    shutil.rmtree(env.cfg.developer_dir / "preludian/myapp/.git")
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--branch", "feat/login"])
    assert result.exit_code == 0, result.output
    assert "warning:" in result.output
    assert "is not a git repository" in result.output
    assert "destroy cannot check" in result.output
    assert not any(f"git -C {WORKDIR}" in c for c in env.runner.commands)
    # The warning comes before any VM work.
    assert result.output.index("warning:") < result.output.index("Cloning")


def test_new_asks_the_branch_with_the_workspace_prefilled(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"], input="\n" + NO_SHELL, interactive=True)
    assert "Git branch [feat-a]:" in result.output
    assert switch_commands(env) == [f"limactl shell {INSTANCE} git -C {WORKDIR} switch -c feat-a"]


def test_new_branch_answer_overrides_the_workspace_name(env):
    ready(env)
    env.invoke(["new", "preludian/myapp", "feat-a"], input="feat/login\n" + NO_SHELL, interactive=True)
    assert switch_commands(env) == [f"limactl shell {INSTANCE} git -C {WORKDIR} switch -c feat/login"]


def test_new_does_not_ask_the_branch_when_a_flag_decides_it(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--no-branch"], input=NO_SHELL, interactive=True)
    assert "Git branch" not in result.output


def test_new_does_not_ask_the_branch_without_git(env):
    ready(env)
    shutil.rmtree(env.cfg.developer_dir / "preludian/myapp/.git")
    result = env.invoke(["new", "preludian/myapp", "feat-a"], input=NO_SHELL, interactive=True)
    assert "Git branch" not in result.output


def test_new_asks_the_workspace_name_when_missing(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp"], input="feat_a\n\n" + NO_SHELL, interactive=True)
    assert result.exit_code == 0, result.output
    assert "Workspace name:" in result.output
    assert "using workspace name feat-a" in result.output
    assert env.runner.find(f"limactl clone --tty=false dev-base {INSTANCE}")


def test_new_asks_the_workspace_again_when_the_answer_sanitises_to_nothing(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp"], input="__\nfeat-a\n\n" + NO_SHELL, interactive=True)
    assert result.exit_code == 0, result.output
    assert "gives an empty name once sanitised" in result.output
    assert result.output.count("Workspace name:") == 2


def test_new_asks_the_project_when_missing_and_fzf_is_absent(env, monkeypatch):
    monkeypatch.setenv("PATH", str(env.tmp_path / "bin"))  # limactl and rsync stubs only, no fzf
    ready(env)
    result = env.invoke(["new"], input="preludian/myapp/\nfeat-a\n\n" + NO_SHELL, interactive=True)
    assert result.exit_code == 0, result.output
    assert "tip: install fzf (brew install fzf)" in result.output
    assert f"Project folder (relative to {env.cfg.developer_dir}):" in result.output
    assert env.runner.find(f"limactl clone --tty=false dev-base {INSTANCE}")


def test_new_asks_the_project_again_after_a_bad_answer(env, monkeypatch):
    monkeypatch.setenv("PATH", str(env.tmp_path / "bin"))
    ready(env)
    answers = "preludian/nope\n" + str(env.cfg.developer_dir / "preludian/myapp") + "\nfeat-a\n\n" + NO_SHELL
    result = env.invoke(["new"], input=answers, interactive=True)
    assert result.exit_code == 0, result.output
    assert "does not exist or is not a directory" in result.output
    assert result.output.count("Project folder") == 2
