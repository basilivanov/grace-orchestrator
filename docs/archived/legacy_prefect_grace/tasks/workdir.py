from __future__ import annotations

from pathlib import Path


def resolve_execution_workdir(candidate: str | None, *, project_root: Path | str | None = None) -> Path:
    if not candidate:
        return Path(project_root).resolve() if project_root else Path.cwd()
    path = Path(str(candidate)).expanduser()
    if path.exists() and path.is_dir():
        return path.resolve()
    return Path(project_root).resolve() if project_root else Path.cwd()
