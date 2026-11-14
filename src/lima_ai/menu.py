"""The menus: the VM picker `lima-ai shell` shows, the checklist `lima-ai destroy` shows,
and the checklist of host hooks `lima-ai new` and `sync-claude` show."""

from collections.abc import Collection
from dataclasses import dataclass

import click

from lima_ai.claude_config import HookChoice, display_command


@dataclass(frozen=True)
class VmRow:
    project: str
    workspace: str
    status: str

    @property
    def running(self) -> bool:
        return self.status == "Running"


def ordered(rows: list[VmRow]) -> list[VmRow]:
    """Running VMs first, each group by project then workspace."""
    return sorted(rows, key=lambda row: (not row.running, row.project, row.workspace))


def choices(rows: list[VmRow]):
    """questionary choices: running VMs first, aligned columns, stopped ones disabled with their status."""
    from questionary import Choice

    rows = ordered(rows)
    width = max(len(row.project) for row in rows)
    return [
        Choice(
            f"{row.project.ljust(width)}  {row.workspace}",
            value=(row.project, row.workspace),
            disabled=None if row.running else row.status,
        )
        for row in rows
    ]


def destroy_choices(rows: list[VmRow]):
    """questionary choices for the destroy checklist: every VM selectable, its status in a third column."""
    from questionary import Choice

    rows = ordered(rows)
    project_width = max(len(row.project) for row in rows)
    workspace_width = max(len(row.workspace) for row in rows)
    return [
        Choice(
            f"{row.project.ljust(project_width)}  {row.workspace.ljust(workspace_width)}  {row.status}",
            value=(row.project, row.workspace),
        )
        for row in rows
    ]


def choose_vm(rows: list[VmRow], **prompt_kwargs) -> tuple[str, str] | None:
    """Ask which VM to open; None when the user cancels. prompt_kwargs reach questionary.select (tests)."""
    import questionary

    click.secho("Lima-ai", bold=True)
    try:
        return questionary.select("Select your VM", choices(rows), pointer=">", **prompt_kwargs).unsafe_ask()
    except KeyboardInterrupt:
        return None


def choose_vms(rows: list[VmRow], **prompt_kwargs) -> list[tuple[str, str]] | None:
    """Ask which VMs to destroy; [] when none is ticked, None when the user cancels."""
    import questionary

    click.secho("Lima-ai", bold=True)
    try:
        prompt = questionary.checkbox("Select VMs to destroy", destroy_choices(rows), pointer=">", **prompt_kwargs)
        return prompt.unsafe_ask()
    except KeyboardInterrupt:
        return None


def hook_choices(offered: list[HookChoice], ticked: Collection[str], host_home: str):
    """questionary choices for the hook checklist: the command (home as `~`), then the events it runs on."""
    from questionary import Choice

    shown = [display_command(choice.command, host_home) for choice in offered]
    width = max(len(text) for text in shown)
    return [
        Choice(
            f"{text.ljust(width)}  {', '.join(choice.events)}", value=choice.command, checked=choice.command in ticked
        )
        for choice, text in zip(offered, shown, strict=True)
    ]


def choose_hooks(
    offered: list[HookChoice], ticked: Collection[str], host_home: str, **prompt_kwargs
) -> list[str] | None:
    """Ask which host hooks go into the VM; [] when none is ticked, None when the user cancels."""
    import questionary

    click.secho("Lima-ai", bold=True)
    try:
        choices = hook_choices(offered, ticked, host_home)
        prompt = questionary.checkbox("Select the hooks to copy into the VM", choices, pointer=">", **prompt_kwargs)
        return prompt.unsafe_ask()
    except KeyboardInterrupt:
        return None
