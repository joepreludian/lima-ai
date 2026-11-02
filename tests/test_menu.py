from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from lima_ai import menu
from lima_ai.menu import VmRow

DOWN = "\x1b[B"
ENTER = "\r"
CTRL_C = "\x03"
SPACE = " "

ROWS = [
    VmRow("preludian/site", "adjustments", "Running"),
    VmRow("acme/shop", "redesign", "Stopped"),
    VmRow("preludian/myapp", "feat-a", "Running"),
    VmRow("preludian/myapp", "feat-b", "Running"),
]


def run_menu(keys: str, rows=ROWS):
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        return menu.choose_vm(rows, input=pipe, output=DummyOutput())


def test_choices_put_running_vms_first_in_aligned_columns():
    titles = [c.title for c in menu.choices(ROWS)]
    assert titles == [
        "preludian/myapp  feat-a",
        "preludian/myapp  feat-b",
        "preludian/site   adjustments",
        "acme/shop        redesign",
    ]


def test_choices_disable_every_status_but_running():
    rows = [VmRow("a/x", "w", "Running"), VmRow("a/y", "w", "Stopped"), VmRow("a/z", "w", "Broken")]
    assert [c.disabled for c in menu.choices(rows)] == [None, "Stopped", "Broken"]


def test_enter_picks_the_first_running_vm():
    assert run_menu(ENTER) == ("preludian/myapp", "feat-a")


def test_down_then_enter_picks_the_second():
    assert run_menu(DOWN + ENTER) == ("preludian/myapp", "feat-b")


def test_the_cursor_skips_stopped_vms():
    rows = [VmRow("a/x", "w", "Running"), VmRow("a/y", "w", "Stopped"), VmRow("a/z", "w", "Running")]
    assert run_menu(DOWN + ENTER, rows) == ("a/z", "w")


def test_ctrl_c_cancels(capsys):
    assert run_menu(CTRL_C) is None
    assert "Lima-ai" in capsys.readouterr().out


def run_checklist(keys: str, rows=ROWS):
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        return menu.choose_vms(rows, input=pipe, output=DummyOutput())


def test_destroy_choices_show_status_in_a_third_aligned_column():
    titles = [c.title for c in menu.destroy_choices(ROWS)]
    assert titles == [
        "preludian/myapp  feat-a       Running",
        "preludian/myapp  feat-b       Running",
        "preludian/site   adjustments  Running",
        "acme/shop        redesign     Stopped",
    ]


def test_destroy_choices_disable_nothing():
    rows = [VmRow("a/x", "w", "Running"), VmRow("a/y", "w", "Stopped"), VmRow("a/z", "w", "Broken")]
    assert [c.disabled for c in menu.destroy_choices(rows)] == [None, None, None]


def test_checklist_enter_with_nothing_ticked_returns_empty():
    assert run_checklist(ENTER) == []


def test_checklist_space_ticks_the_first_vm():
    assert run_checklist(SPACE + ENTER) == [("preludian/myapp", "feat-a")]


def test_checklist_can_tick_a_stopped_vm():
    assert run_checklist(DOWN + DOWN + DOWN + SPACE + ENTER) == [("acme/shop", "redesign")]


def test_checklist_a_ticks_every_vm():
    assert run_checklist("a" + ENTER) == [
        ("preludian/myapp", "feat-a"),
        ("preludian/myapp", "feat-b"),
        ("preludian/site", "adjustments"),
        ("acme/shop", "redesign"),
    ]


def test_checklist_ctrl_c_cancels(capsys):
    assert run_checklist(CTRL_C) is None
    assert "Lima-ai" in capsys.readouterr().out
