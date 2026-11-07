import dataclasses
import json
import os
import re
import tomllib
import types
import typing
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
    aws_cli: str = "2.39.6"
    aws_cli_sha256: str = "5763332bdcb432c19ee122545856fd350c3bb306753212deedcfccc76f4d20c3"
    ssm_plugin: str = "1.2.896.0"
    ssm_plugin_sha256: str = "914eeca87b18b55356c58be197080f73742b3ca60d3823f0a45670dc9056aa9c"


@dataclass(frozen=True)
class SyncConfig:
    extra_excludes: tuple[str, ...] = ()
    # None: ask before copying ~/.ssh private keys into a VM, then remember the answer here.
    ssh_keys: bool | None = None


@dataclass(frozen=True)
class BaseConfig:
    # A script `lima-ai base` runs as root in dev-base after its own provisioning; None: no hook.
    hook: Path | None = None


@dataclass(frozen=True)
class Config:
    developer_dir: Path = Path("~/Developer")
    backups_dir: Path = Path("~/Developer/backups/docker")
    vm: VmConfig = field(default_factory=VmConfig)
    versions: Versions = field(default_factory=Versions)
    sync: SyncConfig = field(default_factory=SyncConfig)
    base: BaseConfig = field(default_factory=BaseConfig)


SECTIONS = {"vm": VmConfig, "versions": Versions, "sync": SyncConfig, "base": BaseConfig}


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
    hook = cfg.base.hook
    return dataclasses.replace(
        cfg,
        developer_dir=Path(cfg.developer_dir).expanduser(),
        backups_dir=Path(cfg.backups_dir).expanduser(),
        base=dataclasses.replace(cfg.base, hook=hook.expanduser() if hook is not None else None),
    )


def _build(cls, values: dict[str, Any], prefix: str, path: Path, sections: set[str] = frozenset()):
    defaults = cls()
    fields = {f.name: f for f in dataclasses.fields(cls)}
    kwargs = {}
    for key, value in values.items():
        if key not in fields:
            raise LimaAiError("config", f"unknown key '{prefix}{key}' in {path}")
        if key not in sections:
            expected = _expected_type(fields[key].type, getattr(defaults, key))
            value = _check_type(expected, value, f"{prefix}{key}", path)
        kwargs[key] = value
    return cls(**kwargs)


def _expected_type(annotation: Any, default: Any) -> type:
    """The type a setting must have: its default's, or for `X | None` fields the X."""
    if isinstance(annotation, types.UnionType):
        return next(arg for arg in typing.get_args(annotation) if arg is not type(None))
    if isinstance(annotation, type):
        return annotation
    return type(default)  # a generic alias such as tuple[str, ...]


def _check_type(expected: type, value: Any, key: str, path: Path) -> Any:
    if expected is Path:
        ok = isinstance(value, str)
        value = Path(value) if ok else value
    elif expected is tuple:
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        value = tuple(value) if ok else value
    elif expected is bool or isinstance(value, bool):
        ok = type(value) is expected
    else:
        ok = isinstance(value, expected)
    if not ok:
        raise LimaAiError("config", f"'{key}' in {path} must be {_type_name(expected)}")
    return value


def _type_name(expected: type) -> str:
    if expected is bool:
        return "true or false"
    if expected is Path:
        return "a path string"
    if expected is tuple:
        return "a list of strings"
    return {int: "an integer", str: "a string"}.get(expected, expected.__name__)


_ANY_HEADER = re.compile(r"^\s*\[", re.MULTILINE)


def save_setting(section: str, key: str, value: bool | str, path: Path | None = None) -> Path:
    """Write `key = value` under [section] in config.toml, keeping everything else as written."""
    path = path or config_dir() / "config.toml"
    text = path.read_text() if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    rendered = str(value).lower() if isinstance(value, bool) else json.dumps(value)
    line = f"{key} = {rendered}\n"
    header = re.search(rf"^\s*\[\s*{re.escape(section)}\s*\]", text, re.MULTILINE)
    if header is None:
        text += ("\n" if text else "") + f"[{section}]\n" + line
    else:
        # The table body runs from the line after its header to the next header (or the end).
        start = text.index("\n", header.end()) + 1
        following = _ANY_HEADER.search(text, start)
        end = following.start() if following else len(text)
        key_line = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
        body = key_line.sub("", text[start:end], count=1).lstrip("\n")
        text = text[:start] + line + body + text[end:]
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LimaAiError("config", f"{path}: cannot add {key}, fix the file first ({exc})") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def save_ssh_keys(value: bool, path: Path | None = None) -> Path:
    """Write `ssh_keys = true|false` under [sync] in config.toml."""
    return save_setting("sync", "ssh_keys", value, path)
