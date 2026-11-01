"""`lima-ai new` filling in what the command line left out."""

import shutil

from tests.fakes import lima_list
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


def test_new_sanitises_a_workspace_argument_before_it_becomes_the_branch(env):
    ready(env)
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped"), ("dev-myapp-feat-login", "Running")))
    env.runner.on("limactl list --json", lima_list(("dev-base", "Stopped")), times=1)
    result = env.invoke(["new", "preludian/myapp", "Feat_Login"])
    assert result.exit_code == 0, result.output
    assert "using workspace name feat-login" in result.output
    assert switch_commands(env) == [f"limactl shell dev-myapp-feat-login git -C {WORKDIR} switch -c feat-login"]
    assert "Open it with: lima-ai shell preludian/myapp feat-login" in result.output


def test_new_prefills_the_branch_prompt_with_the_sanitised_workspace(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "Feat_Login"], input="\n" + NO_SHELL, interactive=True)
    assert "Git branch [feat-login]:" in result.output


def test_new_does_not_note_the_workspace_name_when_it_is_already_clean(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert "using workspace name" not in result.output


def test_new_rejects_an_empty_branch(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--branch", ""])
    assert result.exit_code == 1
    assert "error [usage]: --branch needs a branch name" in result.output
    assert not env.runner.find("limactl clone")


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


def test_new_switches_to_a_branch_that_already_exists_instead_of_creating_it(env):
    ready(env)
    env.runner.on("rev-parse --verify --quiet refs/heads/feat/login", returncode=0)
    env.invoke(["new", "preludian/myapp", "feat-a", "--branch", "feat/login"])
    assert switch_commands(env) == [f"limactl shell {INSTANCE} git -C {WORKDIR} switch feat/login"]


def test_new_probes_the_branch_before_switching(env):
    ready(env)
    env.invoke(["new", "preludian/myapp", "feat-a"])
    cmds = env.runner.commands
    probe = cmds.index(f"limactl shell {INSTANCE} git -C {WORKDIR} rev-parse --verify --quiet refs/heads/feat-a")
    assert probe < cmds.index(f"limactl shell {INSTANCE} git -C {WORKDIR} switch -c feat-a")


def shell_opens(env):
    return [
        c
        for c in env.runner.calls
        if c.interactive and c.command.startswith(f"limactl shell --workdir {WORKDIR} {INSTANCE}")
    ]


def test_new_offers_a_shell_and_opens_it_on_yes(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--no-branch"], input="y\n", interactive=True)
    assert result.exit_code == 0, result.output
    assert "Open a shell in it now? [Y/n]:" in result.output
    assert len(shell_opens(env)) == 1
    assert result.output.index("Open it with:") < result.output.index("Open a shell in it now?")


def test_new_shell_offer_defaults_to_yes(env):
    ready(env)
    env.invoke(["new", "preludian/myapp", "feat-a", "--no-branch"], input="\n", interactive=True)
    assert len(shell_opens(env)) == 1


def test_new_does_not_open_a_shell_on_no(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--no-branch"], input="n\n", interactive=True)
    assert result.exit_code == 0, result.output
    assert shell_opens(env) == []


def test_new_exits_with_the_shells_status(env):
    ready(env)
    env.runner.on(f"limactl shell --workdir {WORKDIR} {INSTANCE}", returncode=3)
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--no-branch"], input="y\n", interactive=True)
    assert result.exit_code == 3


def test_new_does_not_offer_a_shell_outside_a_terminal(env):
    ready(env)
    result = env.invoke(["new", "preludian/myapp", "feat-a"])
    assert "Open a shell" not in result.output
    assert shell_opens(env) == []


def test_new_does_not_offer_a_shell_after_a_failure(env):
    ready(env)
    env.runner.on("--exclude-from=", returncode=23, stderr="rsync error")
    result = env.invoke(["new", "preludian/myapp", "feat-a", "--no-branch"], input="y\n", interactive=True)
    assert result.exit_code == 1
    assert "Open a shell" not in result.output
    assert shell_opens(env) == []


def with_fzf(env):
    fzf = env.tmp_path / "bin/fzf"
    fzf.write_text("#!/bin/sh\necho 'stub: not for running' >&2\nexit 99\n")
    fzf.chmod(0o755)


def test_new_picks_the_project_with_fzf_when_installed(env):
    with_fzf(env)
    ready(env)
    (env.cfg.developer_dir / "opensource/other").mkdir(parents=True)
    env.runner.on("fzf --prompt", "preludian/myapp  (git)\n")
    result = env.invoke(["new"], input="feat-a\n\n" + NO_SHELL, interactive=True)
    assert result.exit_code == 0, result.output
    fzf = env.runner.find("fzf --prompt")
    assert len(fzf) == 1
    assert fzf[0].argv == ["fzf", "--prompt", "Project> ", "--height", "40%", "--reverse", "--no-multi"]
    assert fzf[0].input == "opensource\nopensource/other\npreludian\npreludian/myapp  (git)\n"
    assert "tip: install fzf" not in result.output
    assert "Project folder" not in result.output
    assert env.runner.find(f"limactl clone --tty=false dev-base {INSTANCE}")


def test_new_aborts_when_fzf_is_cancelled(env):
    with_fzf(env)
    ready(env)
    env.runner.on("fzf --prompt", returncode=130)
    result = env.invoke(["new"], input="feat-a\n", interactive=True)
    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert not env.runner.find("limactl clone")
    assert "Workspace name" not in result.output


def test_new_aborts_when_fzf_finds_no_match(env):
    with_fzf(env)
    ready(env)
    env.runner.on("fzf --prompt", returncode=1, stdout="")
    result = env.invoke(["new"], input="feat-a\n", interactive=True)
    assert result.exit_code == 1
    assert not env.runner.find("limactl clone")
