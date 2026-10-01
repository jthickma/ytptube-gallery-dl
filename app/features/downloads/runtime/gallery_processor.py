from urllib.parse import urlsplit

from app.features.conditions.service import Conditions
from app.features.downloads.items import ItemDTO
from app.features.gallerydl.detect import gallerydl_matches
from app.features.gallerydl.extractor import extract
from app.features.gallerydl.opts import build_options
from app.features.gallerydl.utils import gallerydl_archive_id
from app.library.Events import Events

from .core import Download


async def add_gallery(queue, item, already=None) -> dict:
    """Queue the source itself; DownloadJob retains native recursive processing."""
    try:
        metadata = gallerydl_matches(item.url)
        if not metadata:
            return {"status": "error", "msg": "Gallery-dl has no extractor for this URL."}
        options = build_options(item, queue.config)
        archive_id = gallerydl_archive_id(item.url, metadata)
        if await queue.queue.exists(url=item.url):
            return {"status": "error", "msg": "Source is already in the download queue.", "hidden": True}
        if item.extras.get("gallery_mode") == "expand":
            data = await extract(item.url, options, limit=queue.config.gallerydl_max_items)
            children = [entry for entry in data["entries"] if entry["child"]]
            if children:
                seen = already or set()
                if item.url in seen:
                    return {"status": "ok"}
                seen.add(item.url)
                results = []
                for index, entry in enumerate(children):
                    if entry["url"] in seen:
                        continue
                    results.append(
                        await queue.add(
                            item.new_with(
                                url=entry["url"],
                                extras={
                                    **item.extras,
                                    "gallery_mode": "item",
                                    "gallery_parent": item.url,
                                    "playlist_index": index + 1,
                                    "playlist_count": len(children),
                                },
                            ),
                            already=seen,
                        )
                    )
                failures = [
                    result for result in results if result.get("status") == "error" and not result.get("hidden")
                ]
                return {"status": "error", "msg": failures[0]["msg"]} if failures else {"status": "ok"}
        title = f"{metadata['category']}: {urlsplit(item.url).path.strip('/') or item.url}"
        info = {
            "id": archive_id.split()[1],
            "title": title,
            "url": item.url,
            "webpage_url": item.url,
            "extractor": f"gallerydl_{metadata['category']}",
            **metadata,
        }
        condition = None
        if not item.requeued:
            condition = await Conditions.get_instance().match(
                info=info, ignore_conditions=item.extras.get("ignore_conditions", [])
            )
        if condition:
            if condition.extras.get("ignore_download"):
                return {"status": "ok", "msg": f"Ignored by condition '{condition.name}'."}
            from .item_adder import add

            changed = item.new_with(
                requeued=True,
                preset=condition.extras.get("set_preset") or item.preset,
                cookies=condition.extras.get("set_cookies") or item.cookies,
                gallerydl=condition.cli or item.gallerydl,
            )
            return await add(queue, changed, already=already)
        # Repeated source URLs must be revisitable: native archives skip files,
        # not whole collections, so newly added images are still discovered.
        previous_files = []
        try:
            previous = await queue.done.get(url=item.url)
            if previous.info.engine == "gallerydl" and previous.info.download_dir == options["base-directory"]:
                previous_files = previous.info.files
            await queue.clear([previous.info._id], remove_file=False)
        except KeyError:
            pass
        dto = ItemDTO(
            id=info["id"],
            title=title,
            url=item.url,
            engine="gallerydl",
            gallerydl=item.gallerydl,
            gallery_metadata=metadata,
            files=previous_files,
            is_gallery=True,
            gallery_count=len(previous_files) or None,
            preset=item.preset,
            folder=item.folder,
            download_dir=options["base-directory"],
            temp_dir=queue.config.temp_path,
            cookies=item.cookies,
            template=item.template,
            cli=item.cli,
            options=options,
            extras={**item.extras, "gallerydl_category": metadata["category"], "gallery_mode": "item"},
            is_live=False,
            auto_start=item.auto_start,
            force_start=item.force_start,
            archive_id=archive_id,
        )
        download = await queue.queue.put(Download(info=dto))
        queue._notify.emit(
            Events.ITEM_ADDED,
            data=download.info,
            title="Item Added",
            message=f"Gallery '{title}' added to the download queue.",
        )
        if item.auto_start:
            queue.pool.trigger_download()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "msg": str(exc)}
