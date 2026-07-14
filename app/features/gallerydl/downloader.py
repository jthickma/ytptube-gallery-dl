from __future__ import annotations

import contextlib
import io
import mimetypes
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import gallery_dl

from app.library.Utils import create_cookies_file

from .utils import build_args

if TYPE_CHECKING:
    import logging
    from multiprocessing import Queue

    from app.library.ItemDTO import ItemDTO


def _media_type(path: Path) -> str:
    mimetype, _ = mimetypes.guess_type(path.name)
    if mimetype:
        media_type = mimetype.split("/", 1)[0]
        if media_type in {"image", "video", "audio"}:
            return media_type
    return "file"


def _read_manifest(manifest: Path, download_dir: Path) -> list[dict[str, Any]]:
    if not manifest.exists():
        return []

    base = download_dir.resolve()
    seen: set[str] = set()
    files: list[dict[str, Any]] = []

    def add_file(path: Path) -> None:
        relative = str(path.relative_to(base))
        if relative in seen or not path.is_file():
            return
        seen.add(relative)
        files.append(
            {
                "filename": relative,
                "size": path.stat().st_size,
                "media_type": _media_type(path),
                "mimetype": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            }
        )

    for raw in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = base / path
        path = path.resolve(strict=False)
        try:
            path.relative_to(base)
        except ValueError:
            continue
        if path.is_file():
            add_file(path)
            continue

        # The ZIP/CBZ postprocessor removes the source directory only after
        # per-file hooks run. Resolve its archive from the recorded file path.
        parent = path.parent
        while parent != base and base in parent.parents:
            for suffix in (".zip", ".cbz"):
                archive = Path(f"{parent}{suffix}")
                if archive.is_file():
                    add_file(archive)
            parent = parent.parent
    return files


def _raise_cancelled() -> None:
    raise SystemExit(130)


def _redact_args(args: list[str]) -> list[str]:
    sensitive = {"-p", "--password", "-u", "--username", "--proxy"}
    redacted: list[str] = []
    hide_next = False
    for arg in args:
        if hide_next:
            redacted.append("***")
            hide_next = False
            continue
        name = arg.split("=", 1)[0]
        if name in sensitive:
            redacted.append(f"{name}=***" if "=" in arg else arg)
            hide_next = "=" not in arg
            continue
        redacted.append(arg)
    return redacted


def run_gallery_download(
    *,
    info: ItemDTO,
    download_dir: str,
    temp_dir: str,
    status_queue: Queue[Any],
    logger: logging.Logger,
) -> None:
    manifest = Path(temp_dir) / f"gallery_{info._id}.files"
    cookie_file: Path | None = None

    try:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.unlink(missing_ok=True)
        if info.cookies:
            cookie_file = create_cookies_file(info.cookies, manifest.with_suffix(".cookies.txt"))

        args = build_args(
            url=info.url,
            cli=info.cli,
            download_dir=download_dir,
            template=info.template,
            cookie_file=cookie_file,
            manifest_file=manifest,
        )

        def cancel_gallery(*_: object) -> None:
            _raise_cancelled()

        if os.name == "posix":
            signal.signal(signal.SIGUSR1, cancel_gallery)

        status_queue.put({"id": info._id, "status": "downloading"})
        logger.info(
            "Downloading gallery '%s' from '%s' to '%s'.",
            info.title,
            info.url,
            download_dir,
            extra={
                "download": {
                    "download_id": info._id,
                    "item_id": info.id,
                    "url": info.url,
                    "downloader": "gallery-dl",
                    "gallerydl_args": _redact_args(args[:-1]),
                }
            },
        )
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        original_argv = sys.argv
        try:
            sys.argv = ["gallery-dl", *args]
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                return_code = int(gallery_dl.main() or 0)
        finally:
            sys.argv = original_argv

        stdout = stdout_buffer.getvalue()
        stderr = stderr_buffer.getvalue()
        files = _read_manifest(manifest, Path(download_dir))

        if stdout.strip():
            logger.info(stdout.strip())
        if stderr.strip():
            (logger.error if return_code else logger.info)(stderr.strip())

        if return_code != 0:
            message = stderr.strip().splitlines()[-1] if stderr.strip() else f"gallery-dl exited with {return_code}."
            status_queue.put({"id": info._id, "status": "error", "error": message, "msg": message})
            return

        if not files:
            message = "gallery-dl completed without finding any downloaded media files."
            status_queue.put({"id": info._id, "status": "error", "error": message, "msg": message})
            return

        primary = next((file for file in files if file["media_type"] in {"image", "video", "audio"}), files[0])
        primary_path = str(Path(download_dir) / primary["filename"])
        status_queue.put(
            {
                "id": info._id,
                "status": "finished",
                "final_name": primary_path,
                "gallery_files": files,
                "file_size": sum(int(file["size"]) for file in files),
            }
        )
    except BaseException as exc:
        if isinstance(exc, SystemExit) and exc.code == 130:
            status_queue.put({"id": info._id, "status": "cancelled", "msg": "Download cancelled."})
        else:
            logger.exception("Failed to download gallery '%s'.", info.url)
            status_queue.put({"id": info._id, "status": "error", "error": str(exc), "msg": str(exc)})
    finally:
        manifest.unlink(missing_ok=True)
        if cookie_file:
            cookie_file.unlink(missing_ok=True)
