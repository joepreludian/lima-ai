import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lima_ai.errors import LimaAiError

BASE_INSTANCE = "dev-base"
MAX_HOSTNAME = 63


@dataclass(frozen=True)
class Names:
    project: str  # path relative to developer_dir
    slug: str
    feat: str

    @property
    def instance(self) -> str:
        return f"dev-{self.slug}-{self.feat}"

    @property
    def hostname(self) -> str:
        return f"lima-{self.instance}"

    @property
    def mdns(self) -> str:
        return f"{self.hostname}.local"

    @property
    def workdir(self) -> str:
        """Guest working copy, relative to the guest home."""
        return f"work/{self.slug}"

    def url(self, port: int) -> str:
        return f"http://{self.mdns}:{port}"


def sanitize(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]", "-", value.lower())
    return re.sub(r"-+", "-", value).strip("-")


def resolve(developer_dir: Path, project: str, feat: str) -> Names:
    relative = _relative_project(developer_dir, project)
    slug = sanitize(relative.name)
    if not slug:
        raise LimaAiError("naming", f"project '{project}' gives an empty name once sanitised")
    feat_name = sanitize(feat)
    if not feat_name:
        raise LimaAiError("naming", f"feature '{feat}' gives an empty name once sanitised")
    names = Names(project=relative.as_posix(), slug=slug, feat=feat_name)
    if len(names.hostname) > MAX_HOSTNAME:
        raise LimaAiError(
            "naming",
            f"hostname '{names.hostname}' is {len(names.hostname)} characters; "
            f"the limit is {MAX_HOSTNAME}. Use a shorter feature name.",
        )
    return names


def _relative_project(developer_dir: Path, project: str) -> PurePosixPath:
    path = Path(project).expanduser()
    if path.is_absolute():
        try:
            path = path.relative_to(developer_dir)
        except ValueError:
            raise LimaAiError("naming", f"project '{project}' is not inside {developer_dir}") from None
    relative = PurePosixPath(path.as_posix())
    if not relative.parts or relative.parts == (".",) or ".." in relative.parts:
        raise LimaAiError("naming", f"project '{project}' must be a folder inside {developer_dir}")
    return relative


def project_dir(developer_dir: Path, names: Names) -> Path:
    path = developer_dir / names.project
    if not path.is_dir():
        raise LimaAiError("project", f"{path} does not exist or is not a directory")
    return path
