import asyncio
import functools

from app.features.ytdlp.extractor import ExtractorConfig, ExtractorPool

from .opts import apply_options
from .utils import gallerydl_archive_id, json_safe


def extract_sync(url: str, options: dict, resolve: bool = False, limit: int = 0) -> dict:
    from gallery_dl import exception, job

    apply_options(options)

    class CollectJob(job.DataJob):
        count = 0

        def handle_url(self, url, kwdict):
            super().handle_url(url, kwdict)
            self.count += 1
            if limit and self.count >= limit:
                raise exception.StopExtraction

        def handle_queue(self, url, kwdict):
            super().handle_queue(url, kwdict)
            self.count += 1
            if limit and self.count >= limit:
                raise exception.StopExtraction

    source = CollectJob(url, file=None, resolve=resolve)
    source.run()
    if source.exception:
        raise ValueError(str(source.exception))
    entries = []
    metadata = {}
    for message in source.data:
        if message[0] == 2:
            metadata = message[-1]
        elif message[0] in (3, 6):
            entries.append(
                {
                    "url": message[1],
                    "metadata": json_safe(message[-1]),
                    "child": message[0] == 6,
                    "archive_id": gallerydl_archive_id(message[1], message[-1]),
                }
            )
    return {
        "engine": "gallerydl",
        "category": source.extractor.category,
        "subcategory": source.extractor.subcategory,
        "url": url,
        "title": metadata.get("title") or metadata.get("user") or url,
        "metadata": json_safe(metadata),
        "entries": entries,
        "gallery_count": len(entries),
    }


async def extract(url: str, options: dict, *, resolve: bool = False, limit: int = 0) -> dict:
    from app.library.config import Config

    config = Config.get_instance()
    settings = ExtractorConfig(
        concurrency=config.extract_info_concurrency,
        timeout=config.extract_info_timeout,
        keep_alive=config.extract_info_keep_alive,
    )
    manager = ExtractorPool.get_instance()
    async with manager.get_semaphore(settings):
        pool = manager.get_pool(settings)
        try:
            work = functools.partial(extract_sync, url, options, resolve, limit)
            return await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(pool, work), timeout=settings.timeout
            )
        finally:
            manager.release_pool(pool)
