import hashlib
import json
import mimetypes
from pathlib import Path


def gallerydl_archive_id(url: str, metadata: dict | None = None) -> str:
    """Stable source identity; native gallery-dl archives remain file based."""
    from .detect import gallerydl_matches

    match = metadata or gallerydl_matches(url) or {}
    identity = hashlib.sha256(url.rstrip("/").encode()).hexdigest()[:24]
    return f"gallerydl {match.get('category', 'generic')}:{identity}"


def history_archive() -> str:
    from app.library.config import Config

    return str(Path(Config.get_instance().config_path) / "gallerydl-history.txt")


def json_safe(value):
    return json.loads(json.dumps(value, default=str))


def file_record(path: str | Path, root: str | Path, metadata: dict | None = None) -> dict | None:
    """Only expose finalized files inside this item's download directory."""
    path = Path(path).resolve()
    root = Path(root).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return {
        "filename": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "metadata": json_safe({k: v for k, v in (metadata or {}).items() if not k.startswith("_")}),
    }


def remove_files(item, root: str | Path) -> int:
    """Remove recorded files and matching sidecars, never a shared source folder."""
    import glob

    root = Path(root).resolve()
    base = (root / item.folder).resolve()
    if not base.is_relative_to(root):
        return 0
    removed = 0
    for record in item.files:
        path = (base / record["filename"]).resolve()
        if not path.is_relative_to(base):
            continue
        for candidate in path.parent.glob(f"{glob.escape(path.stem)}.*"):
            if candidate.is_file() and not candidate.is_symlink() and candidate.resolve().is_relative_to(base):
                candidate.unlink(missing_ok=True)
                removed += 1
    return removed
