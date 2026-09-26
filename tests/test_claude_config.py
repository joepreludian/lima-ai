import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lima_ai.claude_config import (
    INCLUDE,
    filter_hooks,
    filter_options,
    rewrite_home,
    stage_transformed,
)

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
    for name in ["CLAUDE.md", "RTK.md", "statusline-command.sh", "history.jsonl", "settings.json.bak",
                 ".credentials.json", "stats-cache.json"]:
        (claude / name).parent.mkdir(parents=True, exist_ok=True)
        (claude / name).write_text(name)
    shutil.copy(FIXTURES / "settings.json", claude / "settings.json")
    for rel in ["skills/demo/SKILL.md", "skills/demo/old.bak", "commands/x.md", "agents/a.md",
                "plugins/cache/p/1.0/plugin.json", "plugins/marketplaces/m/marketplace.json",
                "projects/p/session.jsonl", "sessions/s.json", "file-history/f", "cache/c",
                "backups/b", "debug/d", "shell-snapshots/s", "todos/t.json"]:
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
    assert result["permissions"]["allow"][0] == "Bash(git -C /Users/jon/Developer/preludian/riscofauna log --oneline -5)"
    plugins = json.loads((staging / "plugins/installed_plugins.json").read_text())
    install = plugins["plugins"]["superpowers@claude-plugins-official"][0]["installPath"]
    assert install == "/home/jon.linux/.claude/plugins/cache/claude-plugins-official/superpowers/6.4.1"


def test_stage_transformed_with_nothing_to_transform(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    stage_transformed(claude, tmp_path / "staging", HOST_HOME, GUEST_HOME, DEV)
    assert not any((tmp_path / "staging").rglob("*"))


def test_include_list_matches_spec():
    assert INCLUDE == ("CLAUDE.md", "RTK.md", "settings.json", "statusline-command.sh",
                       "skills", "plugins", "commands", "agents")
