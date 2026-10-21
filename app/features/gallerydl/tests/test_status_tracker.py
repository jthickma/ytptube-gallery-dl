import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.features.downloads.items import ItemDTO
from app.features.downloads.runtime.status_tracker import StatusTracker
from app.features.gallerydl.utils import file_record
from app.library.Events import EventBus


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(EventBus, "get_instance", staticmethod(MagicMock))
    info = ItemDTO(
        id="gallery",
        title="Gallery",
        url="https://vsco.co/fixture/gallery",
        engine="gallerydl",
        folder="",
        download_dir=str(tmp_path),
    )
    return StatusTracker(info, info._id, str(tmp_path), None, MagicMock(), logging.getLogger(__name__))


async def add_file(tracker, root, name, content):
    path = root / name
    path.write_bytes(content)
    await tracker.process_status_update({"id": tracker.id, "action": "file", "file": file_record(path, root)})


@pytest.mark.asyncio
async def test_file_events_do_not_recheck_previously_recorded_files(tracker, tmp_path, monkeypatch):
    await add_file(tracker, tmp_path, "first.png", b"first")
    original = Path.is_file
    checks = []

    def counted(path):
        checks.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "is_file", counted)
    for index in range(20):
        await add_file(tracker, tmp_path, f"image-{index}.png", b"image")

    assert "first.png" not in checks
    assert tracker.info.gallery_count == 21
    assert tracker.info.file_size == 105


@pytest.mark.asyncio
async def test_file_replacement_keeps_order_count_and_sizes(tracker, tmp_path):
    await add_file(tracker, tmp_path, "first.png", b"first")
    await add_file(tracker, tmp_path, "second.png", b"second")
    await add_file(tracker, tmp_path, "first.png", b"replacement")

    assert [file["filename"] for file in tracker.info.files] == ["first.png", "second.png"]
    assert tracker.info.gallery_count == 2
    assert tracker.info.file_size == len(b"replacementsecond")
    assert tracker.info.filename == "first.png"


@pytest.mark.asyncio
async def test_final_reconciliation_retains_archive_files_and_replaces_deleted_postprocessor_inputs(tracker, tmp_path):
    await add_file(tracker, tmp_path, "existing.png", b"existing")
    await add_file(tracker, tmp_path, "replaced.png", b"replaced")
    (tmp_path / "replaced.png").unlink()
    package = tmp_path / "gallery.zip"
    package.write_bytes(b"package")
    await tracker.process_status_update(
        {"id": tracker.id, "action": "files", "files": [file_record(package, tmp_path)]}
    )

    assert [file["filename"] for file in tracker.info.files] == ["existing.png", "gallery.zip"]
    assert tracker.info.gallery_count == 2
    assert tracker.info.file_size == len(b"existingpackage")


@pytest.mark.asyncio
async def test_file_event_never_exposes_an_external_file(tracker, tmp_path):
    await tracker.process_status_update(
        {"id": tracker.id, "action": "file", "file": {"filename": "../outside.png", "size": 100}}
    )
    assert tracker.info.files == []
    assert tracker.info.gallery_count == 0
