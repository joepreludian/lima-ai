"""The VM menus: the picker `lima-ai shell` shows, and the checklist `lima-ai destroy` shows."""

from dataclasses import dataclass

import click


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
