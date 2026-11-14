import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lima_ai.claude_config import (
    INCLUDE,
    HookChoice,
    filter_hooks,
    filter_options,
    offered_hooks,
    push_claude_config,
    rewrite_home,
    stage_transformed,
)
from lima_ai.limactl import Instance
from tests.fakes import FakeRunner

FIXTURES = Path(__file__).parent / "fixtures"
HOST_HOME = "/Users/jon"
GUEST_HOME = "/home/jon.linux"
DEV = "/Users/jon/Developer"


def settings() -> dict:
    return json.loads((FIXTURES / "settings.json").read_text())


def commands(result: dict) -> dict[str, list[str]]:
    return {
        event: [hook["command"] for group in groups for hook in group["hooks"]]
        for event, groups in result["hooks"].items()
    }


def test_drops_hooks_for_uncopied_host_paths_and_keeps_the_rest():
    result = filter_hooks(settings(), HOST_HOME, DEV)
    assert commands(result) == {
        "PreToolUse": ["rtk hook claude"],
        "Stop": ["bash /Users/jon/.claude/statusline-command.sh --stop"],
        "PostToolUse": ["/Users/jon/Developer/tools/format.sh"],
    }


def test_drops_matcher_groups_and_events_left_empty():
    result = filter_hooks(settings(), HOST_HOME, DEV)
    assert result["hooks"]["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}
    ]
    for event in ["SessionStart", "Notification", "UserPromptSubmit"]:
        assert event not in result["hooks"]


def test_tilde_and_home_variable_count_as_host_home():
    result = filter_hooks(settings(), HOST_HOME, DEV)
    assert "Notification" not in result["hooks"]
    assert "UserPromptSubmit" not in result["hooks"]


def test_keeps_permissions_and_other_settings():
    original = settings()
    result = filter_hooks(original, HOST_HOME, DEV)
    assert result["permissions"] == original["permissions"]
    assert result["statusLine"] == original["statusLine"]
    assert original["hooks"]["SessionStart"], "input must not be mutated"


def test_settings_without_hooks_pass_through():
    assert filter_hooks({"theme": "dark"}, HOST_HOME, DEV) == {"theme": "dark"}


def test_rewrite_home_moves_host_home_paths_to_guest_home():
    text = '"bash /Users/jon/.claude/statusline-command.sh", "Read(//Users/jon/.claude/x/**)"'
    assert rewrite_home(text, HOST_HOME, GUEST_HOME, DEV) == (
        '"bash /home/jon.linux/.claude/statusline-command.sh", "Read(//home/jon.linux/.claude/x/**)"'
    )


def test_rewrite_home_keeps_developer_dir_paths_which_are_mounted_as_is():
    text = "git -C /Users/jon/Developer/app log; /Users/jon/Developer; /Users/jon/Developers/x"
    assert rewrite_home(text, HOST_HOME, GUEST_HOME, DEV) == (
        "git -C /Users/jon/Developer/app log; /Users/jon/Developer; /home/jon.linux/Developers/x"
    )


def test_rewrite_home_does_not_touch_other_users():
    assert rewrite_home("/Users/jonas/x", HOST_HOME, GUEST_HOME, DEV) == "/Users/jonas/x"


def make_claude_dir(root: Path) -> Path:
    claude = root / ".claude"
    for name in [
        "CLAUDE.md",
        "RTK.md",
        "statusline-command.sh",
        "history.jsonl",
        "settings.json.bak",
        ".credentials.json",
        "stats-cache.json",
    ]:
        (claude / name).parent.mkdir(parents=True, exist_ok=True)
        (claude / name).write_text(name)
    shutil.copy(FIXTURES / "settings.json", claude / "settings.json")
    for rel in [
        "skills/demo/SKILL.md",
        "skills/demo/old.bak",
        "commands/x.md",
        "agents/a.md",
        "plugins/cache/p/1.0/plugin.json",
        "plugins/marketplaces/m/marketplace.json",
        "projects/p/session.jsonl",
        "sessions/s.json",
        "file-history/f",
        "cache/c",
        "backups/b",
        "debug/d",
        "shell-snapshots/s",
        "todos/t.json",
    ]:
        (claude / rel).parent.mkdir(parents=True, exist_ok=True)
        (claude / rel).write_text(rel)
    shutil.copy(FIXTURES / "installed_plugins.json", claude / "plugins/installed_plugins.json")
    return claude


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_filter_copies_only_the_include_list(tmp_path):
    claude = make_claude_dir(tmp_path / "home")
    dest = tmp_path / "dest"
    subprocess.run(["rsync", "-a", *filter_options(), f"{claude}/", f"{dest}/"], check=True)
    copied = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert copied == [
        "CLAUDE.md",
        "RTK.md",
        "agents/a.md",
        "commands/x.md",
        "plugins/cache/p/1.0/plugin.json",
        "plugins/marketplaces/m/marketplace.json",
        "skills/demo/SKILL.md",
        "statusline-command.sh",
    ]


def test_stage_transformed_writes_filtered_settings_and_rewritten_plugin_json(tmp_path):
    claude = make_claude_dir(tmp_path / "home")
    staging = tmp_path / "staging"
    stage_transformed(claude, staging, HOST_HOME, GUEST_HOME, DEV)
    staged = sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file())
    assert staged == ["plugins/installed_plugins.json", "settings.json"]
    result = json.loads((staging / "settings.json").read_text())
    assert result["statusLine"]["command"] == "bash /home/jon.linux/.claude/statusline-command.sh"
    assert "SessionStart" not in result["hooks"]
    assert (
        result["permissions"]["allow"][0] == "Bash(git -C /Users/jon/Developer/preludian/riscofauna log --oneline -5)"
    )
    plugins = json.loads((staging / "plugins/installed_plugins.json").read_text())
    install = plugins["plugins"]["superpowers@claude-plugins-official"][0]["installPath"]
    assert install == "/home/jon.linux/.claude/plugins/cache/claude-plugins-official/superpowers/6.4.1"


def test_stage_transformed_with_nothing_to_transform(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    stage_transformed(claude, tmp_path / "staging", HOST_HOME, GUEST_HOME, DEV)
    assert not any((tmp_path / "staging").rglob("*"))


def test_include_list_matches_spec():
    assert INCLUDE == (
        "CLAUDE.md",
        "RTK.md",
        "settings.json",
        "statusline-command.sh",
        "skills",
        "plugins",
        "commands",
        "agents",
    )


# --- choosing hooks ----------------------------------------------------------------


def hook_home(tmp_path: Path) -> tuple[str, str]:
    """A host home with hook scripts on disk; returns (home, developer_dir)."""
    home = tmp_path / "home"
    for rel in [".claude-display/push-event.sh", ".claude/hooks/block.sh", "Developer/tools/format.sh"]:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("#!/bin/sh\n")
    (home / ".claude-display/assets").mkdir()
    return str(home), str(home / "Developer")


def hook_settings(home: str) -> dict:
    def entry(command, matcher=None):
        group = {"hooks": [{"type": "command", "command": command}]}
        return {**group, "matcher": matcher} if matcher else group

    push = f"{home}/.claude-display/push-event.sh"
    return {
        "hooks": {
            "SessionStart": [entry(push)],
            "PreToolUse": [
                entry(push, "*"),
                entry(f"{home}/.claude/hooks/block.sh", "Bash"),
                entry("rtk hook claude", "Bash"),
            ],
            "Stop": [entry(push), entry("~/.claude-display/push-event.sh")],
            "PostToolUse": [entry(f"{home}/Developer/tools/format.sh", "Edit")],
            "Notification": [entry(f"{home}/.claude-display/assets"), entry(f"{home}/bin/gone.sh")],
            "UserPromptSubmit": [entry(f"{home}/My Scripts/a.sh")],
        }
    }


def test_offered_hooks_are_the_dropped_ones_whose_script_is_a_file(tmp_path):
    home, dev = hook_home(tmp_path)
    # Not offered: rtk (no path), format.sh (mounted), a directory, a missing file, a path with a space.
    assert offered_hooks(hook_settings(home), home, dev) == [
        HookChoice(
            f"{home}/.claude-display/push-event.sh",
            ("SessionStart", "PreToolUse", "Stop"),
            (".claude-display/push-event.sh",),
        ),
        HookChoice(f"{home}/.claude/hooks/block.sh", ("PreToolUse (Bash)",), (".claude/hooks/block.sh",)),
        HookChoice("~/.claude-display/push-event.sh", ("Stop",), (".claude-display/push-event.sh",)),
    ]


@pytest.mark.parametrize(
    "hooks",
    [
        "nope",
        {"Stop": "nope"},
        {"Stop": ["nope"]},
        {"Stop": [{"matcher": "x"}]},
        {"Stop": [{"hooks": [{"type": "prompt", "prompt": "hi"}, "nope", {"command": 3}]}]},
    ],
)
def test_offered_hooks_skip_shapes_they_do_not_know(tmp_path, hooks):
    home, dev = hook_home(tmp_path)
    assert offered_hooks({"hooks": hooks}, home, dev) == []


def test_filter_hooks_keeps_the_named_commands(tmp_path):
    home, dev = hook_home(tmp_path)
    block = f"{home}/.claude/hooks/block.sh"
    result = filter_hooks(hook_settings(home), home, dev, keep={block})
    assert commands(result) == {
        "PreToolUse": [block, "rtk hook claude"],
        "PostToolUse": [f"{home}/Developer/tools/format.sh"],
    }


def test_stage_transformed_rewrites_a_kept_hook_to_the_guest_home(tmp_path):
    home, dev = hook_home(tmp_path)
    claude = Path(home) / ".claude"
    (claude / "settings.json").write_text(json.dumps(hook_settings(home)))
    stage_transformed(claude, tmp_path / "staging", home, GUEST_HOME, dev, keep={f"{home}/.claude/hooks/block.sh"})
    staged = json.loads((tmp_path / "staging/settings.json").read_text())
    assert commands(staged)["PreToolUse"] == ["/home/jon.linux/.claude/hooks/block.sh", "rtk hook claude"]


def push(tmp_path: Path, keep: list[str]) -> FakeRunner:
    home, dev = hook_home(tmp_path)
    (Path(home) / ".claude/settings.json").write_text(json.dumps(hook_settings(home)))
    runner = FakeRunner()
    instance = Instance(name="x", status="Running", dir=tmp_path / "x", ssh_config=tmp_path / "x/ssh.config")
    push_claude_config(runner, instance, GUEST_HOME, Path(dev), Path(home), keep_hooks=keep)
    return runner


def test_push_copies_each_kept_script_once_from_the_host_home(tmp_path, capsys):
    home = tmp_path / "home"
    runner = push(tmp_path, [f"{home}/.claude-display/push-event.sh", "~/.claude-display/push-event.sh"])
    [call] = runner.find("--relative")
    assert call.cwd == home
    assert call.argv[-2:] == [".claude-display/push-event.sh", "lima-x:"]
    assert "--copy-links" in call.argv
    assert runner.calls.index(call) < len(runner.calls) - 1  # before the staged settings.json goes over
    assert "hooks kept: ~/.claude-display/push-event.sh, ~/.claude-display/push-event.sh" in capsys.readouterr().err


def test_push_ignores_a_kept_command_that_is_no_longer_offered(tmp_path):
    runner = push(tmp_path, [f"{tmp_path}/home/bin/gone.sh"])
    assert not runner.find("--relative")


def test_push_without_kept_hooks_runs_no_extra_rsync(tmp_path, capsys):
    runner = push(tmp_path, [])
    assert not runner.find("--relative")
    assert "hooks kept" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "hooks",
    [
        "nope",
        {"Stop": "nope"},
        {"Stop": None},
        {"Stop": ["nope"]},
        {"Stop": [{"matcher": "x"}]},
        {"Stop": [{"hooks": None}]},
        {"Stop": [{"hooks": [{"type": "prompt", "prompt": "hi"}, "nope", {"command": 3}, {"command": ["a"]}]}]},
    ],
)
def test_filter_hooks_leaves_shapes_it_does_not_know_alone(tmp_path, hooks):
    home, dev = hook_home(tmp_path)
    assert filter_hooks({"hooks": hooks}, home, dev, keep={"x"}) == {"hooks": hooks}


def test_a_quoted_or_escaped_path_with_a_space_is_offered_whole(tmp_path):
    home, dev = hook_home(tmp_path)
    (Path(home) / "My Scripts").mkdir()
    (Path(home) / "My Scripts/a.sh").write_text("#!/bin/sh\n")
    quoted, single, escaped = f'"{home}/My Scripts/a.sh" --go', "'~/My Scripts/a.sh'", f"{home}/My\\ Scripts/a.sh"
    settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": c} for c in (quoted, single, escaped)]}]}}
    assert offered_hooks(settings, home, dev) == [
        HookChoice(command, ("Stop",), ("My Scripts/a.sh",)) for command in (quoted, single, escaped)
    ]


def test_an_unquoted_path_with_a_space_is_what_the_shell_would_run(tmp_path):
    home, dev = hook_home(tmp_path)
    (Path(home) / "My").write_text("#!/bin/sh\n")
    settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"{home}/My Scripts/a.sh"}]}]}}
    assert offered_hooks(settings, home, dev) == [HookChoice(f"{home}/My Scripts/a.sh", ("Stop",), ("My",))]


def test_a_path_with_a_parent_step_is_not_offered(tmp_path):
    home, dev = hook_home(tmp_path)
    commands_ = [f"{home}/.claude-display/../.claude-display/push-event.sh", "~/../outside.sh"]
    settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": c} for c in commands_]}]}}
    assert offered_hooks(settings, home, dev) == []
    assert filter_hooks(settings, home, dev) == {"hooks": {}}


def test_push_leaves_existing_guest_directories_as_they_are(tmp_path):
    runner = push(tmp_path, [f"{tmp_path}/home/.claude/hooks/block.sh"])
    [call] = runner.find("--relative")
    assert "--no-implied-dirs" in call.argv
