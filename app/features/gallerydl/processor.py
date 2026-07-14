from __future__ import annotations

import hashlib
from email.utils import formatdate
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.library.downloads import Download
from app.library.Events import Events
from app.library.ItemDTO import ItemDTO
from app.library.Utils import calc_download_path, validate_url

from .utils import DOWNLOADER, parse_cli

if TYPE_CHECKING:
    from app.library.downloads.queue_manager import DownloadQueue
    from app.library.ItemDTO import Item


async def add_gallery(queue: DownloadQueue, item: Item) -> dict[str, str]:
    try:
        validate_url(item.url, queue.config.allow_internal_urls)
        parse_cli(item.cli)
        download_dir = calc_download_path(queue.config.download_path, item.folder)
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}

    existing = await queue.queue.get_item(url=item.url, downloader=DOWNLOADER)
    if existing:
        return {"status": "error", "msg": "This gallery URL is already in the download queue."}

    parsed = urlparse(item.url)
    display_path = parsed.path.rstrip("/").split("/")[-1]
    title = display_path or parsed.netloc or item.url
    source_id = hashlib.sha256(item.url.encode()).hexdigest()[:16]
    extras = {**item.extras, "downloader": DOWNLOADER, "gallery_files": []}

    info = ItemDTO(
        id=source_id,
        title=title,
        url=item.url,
        preset=item.preset,
        folder=item.folder,
        download_dir=download_dir,
        temp_dir=queue.config.temp_path,
        cookies=item.cookies,
        template=item.template or None,
        datetime=formatdate(),
        cli=item.cli,
        auto_start=item.auto_start,
        downloader=DOWNLOADER,
        extras=extras,
    )
    download = Download(info=info)
    await queue.queue.put(download)
    if item.auto_start:
        queue.pool.trigger_download()

    queue._notify.emit(
        Events.ITEM_ADDED,
        data=download.info,
        title="Gallery Added",
        message=f"Gallery '{download.info.title}' has been added to the download queue.",
    )
    return {"status": "ok"}

