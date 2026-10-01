import asyncio
import base64
import functools
import http.server
import logging
import multiprocessing
import queue
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from gallery_dl import config as gallery_config, extractor
from gallery_dl.extractor.vsco import VscoGalleryExtractor

from app.features.downloads.items import Item, ItemDTO
from app.features.downloads.runtime.status_tracker import StatusTracker
from app.features.gallerydl.detect import resolve_engine
from app.features.gallerydl.extractor import extract_sync
from app.features.gallerydl.opts import GalleryDLOpts, build_options, gallerydl_arg_converter
from app.features.gallerydl.runner import GalleryDLRunner
from app.features.gallerydl.utils import file_record, remove_files
from app.features.presets.schemas import Preset
from app.features.tasks.schemas import Task
from app.library.config import Config

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aHAAAAABJRU5ErkJggg==")


@pytest.fixture
def media_server(tmp_path):
    served = tmp_path / "server"
    served.mkdir()
    (served / "image.png").write_bytes(PNG)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(served)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/image.png"
    server.shutdown()
    server.server_close()
    thread.join()


def make_item(tmp_path, url="https://vsco.co/fixture/gallery"):
    root = tmp_path / "downloads"
    root.mkdir(exist_ok=True)
    return SimpleNamespace(_id="test-gallery", url=url, download_dir=str(root))


def make_options(item, tmp_path):
    return {
        "base-directory": item.download_dir,
        "extractor": {"archive": str(tmp_path / "archive.sqlite3"), "archive-event": "after", "retries": 0},
        "output": {"mode": "null"},
        "cache": {"file": str(tmp_path / "cache.sqlite3")},
    }


def photos(url, count):
    return [
        {
            "_id": str(i),
            "responsive_url": url,
            "is_video": False,
            "upload_date": 1000,
            "grid_name": "fixture",
            "width": 1,
            "height": 1,
        }
        for i in range(count)
    ]


def updates(status):
    result = []
    while not status.empty():
        result.append(status.get_nowait())
    return result


def test_full_vsco_gallery_preserves_native_parent_folder_and_archive(tmp_path, media_server, monkeypatch):
    monkeypatch.setattr(VscoGalleryExtractor, "images", lambda self: photos(media_server, 205))
    item = make_item(tmp_path)
    status = queue.Queue()
    runner = GalleryDLRunner(item, make_options(item, tmp_path), status)
    assert runner.run() == 0
    files = list((Path(item.download_dir) / "vsco" / "fixture").glob("*.png"))
    assert len(files) == 205
    events = updates(status)
    assert len([event for event in events if event.get("action") == "file"]) == 205
    assert len(events[-2]["files"]) == 205
    assert events[-1]["status"] == "finished"
    with sqlite3.connect(tmp_path / "archive.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM archive").fetchone()[0] == 205
    # Existing files are skipped, and new images in a source remain discoverable.
    monkeypatch.setattr(VscoGalleryExtractor, "images", lambda self: photos(media_server, 206))
    repeat = GalleryDLRunner(item, make_options(item, tmp_path), queue.Queue())
    assert repeat.run() == 0
    assert repeat.skipped == 205
    assert len(repeat.files) == 206


def test_direct_image_and_metadata_enumeration(tmp_path, media_server):
    item = make_item(tmp_path, media_server)
    options = make_options(item, tmp_path)
    data = extract_sync(item.url, options)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["metadata"]["extension"] == "png"
    runner = GalleryDLRunner(item, options, queue.Queue())
    assert runner.run() == 0
    assert next(iter(runner.files.values()))["mime"] == "image/png"


def test_child_jobs_keep_hooks_and_file_list(tmp_path, media_server, monkeypatch):
    from gallery_dl.extractor.common import Extractor, Message

    class Parent(Extractor):
        category = "fixture"
        subcategory = "gallery"
        directory_fmt = ("fixture",)

        def items(self):
            yield Message.Directory, "", {}
            yield Message.Queue, media_server, {}

    original = extractor.find
    monkeypatch.setattr(
        extractor,
        "find",
        lambda url: Parent(__import__("re").match(".*", url)) if url == "fixture:parent" else original(url),
    )
    item = make_item(tmp_path, "fixture:parent")
    status = queue.Queue()
    runner = GalleryDLRunner(item, make_options(item, tmp_path), status)
    assert runner.run() == 0
    assert len(runner.files) == 1
    assert updates(status)[-1]["status"] == "finished"


def test_native_metadata_and_zip_postprocessing(tmp_path, media_server, monkeypatch):
    monkeypatch.setattr(VscoGalleryExtractor, "images", lambda self: photos(media_server, 3))
    item = make_item(tmp_path)
    options = {**make_options(item, tmp_path), **gallerydl_arg_converter("--write-metadata --zip")}
    status = queue.Queue()
    runner = GalleryDLRunner(item, options, status)
    assert runner.run() == 0
    assert any(record["filename"].endswith(".zip") for record in runner.files.values())
    assert updates(status)[-1]["status"] == "finished"


def test_cancel_does_not_report_success(tmp_path, media_server, monkeypatch):
    monkeypatch.setattr(VscoGalleryExtractor, "images", lambda self: photos(media_server, 3))
    event = threading.Event()
    event.set()
    item = make_item(tmp_path)
    status = queue.Queue()
    runner = GalleryDLRunner(item, make_options(item, tmp_path), status, cancel_event=event)
    assert runner.run() == 130
    assert updates(status)[-1]["status"] == "cancelled"


@pytest.mark.parametrize(
    "raw", ["--unknown", "--help", "--version", "--dump-json", "https://example.com", '{"extractor":']
)
def test_invalid_options_raise_without_exiting(raw):
    with pytest.raises(ValueError):
        gallerydl_arg_converter(raw)


def test_options_dialect_and_precedence(tmp_path, monkeypatch):
    options = (
        GalleryDLOpts()
        .add_raw("--retries 2 -o extractor.vsco.videos=false")
        .add_raw("--retries 7 --write-metadata")
        .get_all()
    )
    assert options["retries"] == 7
    assert options["extractor"]["vsco"]["videos"] is False
    assert options["postprocessors"] == ["metadata"]
    config = Config.get_instance()
    monkeypatch.setattr(config, "download_path", str(tmp_path))
    item = Item(url="https://vsco.co/fixture/gallery", engine="gallerydl", gallerydl="--range 1-5", preset="")
    assert "directory" not in build_options(item)
    assert "filename" not in build_options(item)
    assert build_options(item)["file-range"] == "1-5"
    assert Preset(name="gallery", engine="gallerydl", cli="--write-metadata").engine == "gallerydl"
    assert Task(name="gallery", url=item.url, engine="gallerydl", cli="--write-metadata").gallerydl == ""


def test_engine_selection_and_switches(monkeypatch):
    config = Config.get_instance()
    assert resolve_engine("https://vsco.co/fixture/gallery") == "gallerydl"
    assert resolve_engine("https://www.youtube.com/watch?v=BaW_jenozKc") == "ytdlp"
    assert resolve_engine("https://vsco.co/fixture/gallery", "ytdlp") == "ytdlp"
    monkeypatch.setattr(config, "gallerydl_exclude_sites", "vsco")
    assert resolve_engine("https://vsco.co/fixture/gallery") == "ytdlp"
    assert resolve_engine("https://vsco.co/fixture/gallery", "gallerydl") == "gallerydl"


@pytest.fixture
def status_queue():
    status = multiprocessing.Queue()
    try:
        yield status
    finally:
        status.close()
        status.join_thread()


@pytest.mark.asyncio
async def test_tracker_multi_file_finishes_once(tmp_path, monkeypatch, status_queue):
    config = Config.get_instance()
    monkeypatch.setattr(config, "config_path", str(tmp_path))
    dto = ItemDTO(
        id="source",
        title="Gallery",
        url="https://vsco.co/fixture/gallery",
        engine="gallerydl",
        folder="",
        download_dir=str(tmp_path),
    )
    tracker = StatusTracker(dto, dto._id, str(tmp_path), None, status_queue, logging.getLogger(__name__))
    for name in ("a.png", "b.png"):
        path = tmp_path / name
        path.write_bytes(PNG)
        await tracker.process_status_update({"id": dto._id, "action": "file", "file": file_record(path, tmp_path)})
        assert not tracker.final_update
    await tracker.process_status_update({"id": dto._id, "final_name": str(tmp_path / "a.png")})
    assert dto.filename == "a.png"
    assert dto.gallery_count == 2
    assert dto.file_size == 2 * len(PNG)
    assert dto.extras["is_image"]
    assert dto.status == "finished"


def test_removal_does_not_delete_shared_or_external_files(tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    root = tmp_path / "root"
    root.mkdir()
    for name in ("one.png", "one.json", "unrelated.png"):
        (root / name).write_bytes(PNG)
    item = SimpleNamespace(folder="", files=[{"filename": "one.png"}, {"filename": "../outside.png"}])
    assert remove_files(item, root) == 2
    assert outside.exists()
    assert (root / "unrelated.png").exists()
