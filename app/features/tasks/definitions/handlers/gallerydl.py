from app.features.downloads.items import Item
from app.features.gallerydl.detect import resolve_engine
from app.features.gallerydl.extractor import extract
from app.features.gallerydl.opts import build_options
from app.features.gallerydl.utils import gallerydl_archive_id
from app.features.presets.service import Presets
from app.features.tasks.definitions.results import TaskFailure, TaskItem, TaskResult

from ._base_handler import BaseHandler


class GalleryDLTaskHandler(BaseHandler):
    @staticmethod
    async def can_handle(task) -> bool:
        return resolve_engine(task.url, task.engine, Presets.get_instance().get(task.preset)) == "gallerydl"

    @staticmethod
    async def extract(task, config=None):  # noqa: ARG004
        # Schedule the source once per run. The native file archive performs
        # incremental discovery and must not be replaced by URL-level filtering.
        return TaskResult(
            items=[TaskItem(url=task.url, title=task.name, archive_id=gallerydl_archive_id(task.url))],
            metadata={"engine": "gallerydl", "gallery_mode": "item"},
        )

    @classmethod
    async def inspect(cls, task, config=None, *, resolve_ids=True):  # noqa: ARG003
        try:
            item = Item(
                url=task.url,
                engine="gallerydl",
                gallerydl=task.gallerydl,
                preset=task.preset,
                cli=task.cli,
                folder=task.folder,
                template=task.template,
            )
            data = await extract(task.url, build_options(item, config), resolve=False)
            return TaskResult(
                items=[
                    TaskItem(
                        url=entry["url"],
                        title=str(entry["metadata"].get("title") or entry["metadata"].get("filename") or entry["url"]),
                        archive_id=entry["archive_id"],
                        metadata=entry["metadata"],
                    )
                    for entry in data["entries"]
                ],
                metadata={"engine": "gallerydl", "title": data["title"], "gallery_count": data["gallery_count"]},
            )
        except Exception as exc:
            return TaskFailure(message="Gallery-dl inspection failed.", error=str(exc))
