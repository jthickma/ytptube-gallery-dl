import logging
import queue
import sys
from pathlib import Path

from app.features.gallerydl.downloader import _read_manifest, run_gallery_download
from app.library.ItemDTO import ItemDTO


def test_read_manifest_keeps_safe_existing_media(tmp_path: Path) -> None:
    image = tmp_path / "site" / "post" / "image.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"outside")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(f"{image}\n{image}\n{outside}\n", encoding="utf-8")

    files = _read_manifest(manifest, tmp_path)

    assert files == [
        {
            "filename": "site/post/image.jpg",
            "size": 5,
            "media_type": "image",
            "mimetype": "image/jpeg",
        }
    ]


def test_read_manifest_resolves_zip_postprocessor_output(tmp_path: Path) -> None:
    archive = tmp_path / "site" / "post.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"archive")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(
        f"{tmp_path / 'site' / 'post' / 'one.jpg'}\n{tmp_path / 'site' / 'post' / 'two.jpg'}\n",
        encoding="utf-8",
    )

    assert _read_manifest(manifest, tmp_path) == [
        {
            "filename": "site/post.zip",
            "size": 7,
            "media_type": "file",
            "mimetype": "application/zip",
        }
    ]


def test_run_gallery_download_uses_embedded_module(monkeypatch, tmp_path: Path) -> None:
    download_dir = tmp_path / "downloads"
    temp_dir = tmp_path / "tmp"
    status_queue: queue.Queue = queue.Queue()
    original_argv = sys.argv

    def fake_main() -> int:
        manifest = Path(sys.argv[sys.argv.index("--Print-to-file") + 2])
        target = download_dir / "site" / "image.jpg"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"image")
        manifest.write_text(f"{target}\n", encoding="utf-8")
        return 0

    monkeypatch.setattr("app.features.gallerydl.downloader.gallery_dl.main", fake_main)
    info = ItemDTO(
        id="post-1",
        title="Gallery",
        url="https://example.com/gallery/1",
        folder="",
        download_dir=str(download_dir),
        temp_dir=str(temp_dir),
        downloader="gallery-dl",
    )

    run_gallery_download(
        info=info,
        download_dir=str(download_dir),
        temp_dir=str(temp_dir),
        status_queue=status_queue,
        logger=logging.getLogger("gallery-test"),
    )

    assert sys.argv is original_argv
    assert status_queue.get_nowait()["status"] == "downloading"
    finished = status_queue.get_nowait()
    assert finished["status"] == "finished"
    assert finished["gallery_files"][0]["filename"] == "site/image.jpg"
