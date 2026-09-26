import dataclasses
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lima_ai.errors import LimaAiError


@dataclass(frozen=True)
class VmConfig:
    cpus: int = 4
    memory: str = "8GiB"
    disk: str = "60GiB"
    ubuntu_release: str = "26.04"


@dataclass(frozen=True)
class Versions:
    node_major: int = 24
    rtk: str = "0.49.0"
    rtk_sha256: str = "c8ea4b6560841e73157c134fd4a3293914c6ede42e786ee985cf491fde691ba7"
    docker_backup: str = "0.4.0"
    docker_backup_sha256: str = "9c7bdf7c25d4f8c19253a3ffd73bfd34e2d8d4f6e1cd7736b27feffbee8a22d8"


@dataclass(frozen=True)
class SyncConfig:
    extra_excludes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    developer_dir: Path = Path("~/Developer")
    backups_dir: Path = Path("~/Developer/backups/docker")
    app_port: int = 8002
    vm: VmConfig = field(default_factory=VmConfig)
    versions: Versions = field(default_factory=Versions)
    sync: SyncConfig = field(default_factory=SyncConfig)


SECTIONS = {"vm": VmConfig, "versions": Versions, "sync": SyncConfig}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "lima-ai"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
    return Path(base) / "lima-ai"


def load_config(path: Path | None = None) -> Config:
    """Defaults from this module, overridden by the optional TOML file."""
    path = path or config_dir() / "config.toml"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise LimaAiError("config", f"{path}: {exc}") from None

    top: dict[str, Any] = {}
    for key, value in data.items():
        if key in SECTIONS:
            if not isinstance(value, dict):
                raise LimaAiError("config", f"'{key}' must be a table in {path}")
            top[key] = _build(SECTIONS[key], value, f"{key}.", path)
        else:
            top[key] = value
    cfg = _build(Config, top, "", path, sections=set(SECTIONS))
    return dataclasses.replace(
        cfg,
        developer_dir=Path(cfg.developer_dir).expanduser(),
        backups_dir=Path(cfg.backups_dir).expanduser(),
    )


def _build(cls, values: dict[str, Any], prefix: str, path: Path, sections: set[str] = frozenset()):
    defaults = cls()
    known = {f.name for f in dataclasses.fields(cls)}
    kwargs = {}
    for key, value in values.items():
        if key not in known:
            raise LimaAiError("config", f"unknown key '{prefix}{key}' in {path}")
        if key not in sections:
            value = _check_type(getattr(defaults, key), value, f"{prefix}{key}", path)
        kwargs[key] = value
    return cls(**kwargs)


def _check_type(default: Any, value: Any, key: str, path: Path) -> Any:
    if isinstance(default, Path):
        ok = isinstance(value, str)
        value = Path(value) if ok else value
    elif isinstance(default, tuple):
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        value = tuple(value) if ok else value
    elif isinstance(default, bool) or isinstance(value, bool):
        ok = type(value) is type(default)
    else:
        ok = isinstance(value, type(default))
    if not ok:
        raise LimaAiError("config", f"'{key}' in {path} must be {_type_name(default)}")
    return value


def _type_name(default: Any) -> str:
    if isinstance(default, Path):
        return "a path string"
    if isinstance(default, tuple):
        return "a list of strings"
    return {int: "an integer", str: "a string"}.get(type(default), type(default).__name__)
