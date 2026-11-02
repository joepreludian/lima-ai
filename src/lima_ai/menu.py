"""The VM picker `lima-ai shell` shows when several workspace VMs are running."""

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


def choices(rows: list[VmRow]):
    """questionary choices: running VMs first, aligned columns, stopped ones disabled with their status."""
    from questionary import Choice

    ordered = sorted(rows, key=lambda row: (not row.running, row.project, row.workspace))
    width = max(len(row.project) for row in ordered)
    return [
        Choice(
            f"{row.project.ljust(width)}  {row.workspace}",
            value=(row.project, row.workspace),
            disabled=None if row.running else row.status,
        )
        for row in ordered
    ]


def choose_vm(rows: list[VmRow], **prompt_kwargs) -> tuple[str, str] | None:
    """Ask which VM to open; None when the user cancels. prompt_kwargs reach questionary.select (tests)."""
    import questionary

    click.secho("Lima-ai", bold=True)
    try:
        return questionary.select("Select your VM", choices(rows), pointer=">", **prompt_kwargs).unsafe_ask()
    except KeyboardInterrupt:
        return None
