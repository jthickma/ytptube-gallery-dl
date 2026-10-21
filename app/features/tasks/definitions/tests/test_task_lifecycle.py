from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.downloads.runtime.queue_manager import DownloadQueue
from app.features.tasks.definitions.results import HandleTask, TaskFailure, TaskItem, TaskResult
from app.features.tasks.definitions.service import TaskHandle
from app.features.tasks.models import TaskModel
from app.features.tasks.service import Tasks
from app.library.Events import EventBus, Events
from app.library.Services import Services
from app.library.config import Config


def _task() -> HandleTask:
    return HandleTask(
        id=7,
        name="Example",
        url="https://example.com",
        preset="default",
        ignore_conditions=["12", "Named"],
    )


@pytest.mark.asyncio
async def test_dispatch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TaskHandle.__new__(TaskHandle)
    service.dispatch = AsyncMock(return_value=TaskResult(items=[]))
    events = MagicMock()
    monkeypatch.setattr(EventBus, "get_instance", staticmethod(lambda: events))

    await service._dispatch(_task(), MagicMock(), 0)

    task_events = [call.args[0] for call in events.emit.call_args_list if call.args[0].startswith("task_")]
    assert task_events == [Events.TASK_FINISHED]


@pytest.mark.asyncio
async def test_dispatch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TaskHandle.__new__(TaskHandle)
    service.dispatch = AsyncMock(return_value=TaskFailure(message="Extraction failed"))
    events = MagicMock()
    monkeypatch.setattr(EventBus, "get_instance", staticmethod(lambda: events))

    await service._dispatch(_task(), MagicMock(), 0)

    assert [call.args[0] for call in events.emit.call_args_list] == [Events.TASK_ERROR]


@pytest.mark.asyncio
async def test_queue_error(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = DownloadQueue.__new__(DownloadQueue)
    events = MagicMock()
    queue._notify = events
    item = MagicMock(extras={"source_handler": "web", "source_id": 7, "source_name": "Example"}, preset="default")
    monkeypatch.setattr(
        "app.features.downloads.runtime.queue_manager.add_impl",
        AsyncMock(return_value={"status": "error", "msg": "Invalid URL"}),
    )

    result = await queue.add(item)

    assert result["status"] == "error"
    task_events = [call.args[0] for call in events.emit.call_args_list if call.args[0].startswith("task_")]
    assert task_events == [Events.TASK_ERROR]


@pytest.mark.asyncio
async def test_queue_success(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = DownloadQueue.__new__(DownloadQueue)
    events = MagicMock()
    queue._notify = events
    item = MagicMock(extras={"source_handler": "wEb", "source_id": 7, "source_name": "Example"}, preset="default")
    monkeypatch.setattr(
        "app.features.downloads.runtime.queue_manager.add_impl",
        AsyncMock(return_value={"status": "ok"}),
    )

    await queue.add(item)

    task_events = [call.args[0] for call in events.emit.call_args_list if call.args[0].startswith("task_")]
    assert task_events == [Events.TASK_FINISHED]


@pytest.mark.asyncio
async def test_queue_recursive(monkeypatch: pytest.MonkeyPatch) -> None:
    queue = DownloadQueue.__new__(DownloadQueue)
    events = MagicMock()
    queue._notify = events
    item = MagicMock(extras={"source_handler": "Web", "source_id": 7, "source_name": "Example"}, preset="default")
    monkeypatch.setattr(
        "app.features.downloads.runtime.queue_manager.add_impl",
        AsyncMock(return_value={"status": "ok"}),
    )

    await queue.add(item, already=set())

    assert not [call for call in events.emit.call_args_list if call.args[0].startswith("task_")]


def _scheduled_task() -> TaskModel:
    return TaskModel(
        id=7,
        name="Example",
        url="https://example.com",
        preset="default",
        folder="",
        template="",
        engine="auto",
        gallerydl="",
        cli="",
        ignore_conditions=["12", "Named"],
        auto_start=True,
        enabled=True,
    )


@pytest.mark.asyncio
async def test_runner_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = Tasks.__new__(Tasks)
    monkeypatch.setattr(service, "_repo", MagicMock(get=AsyncMock(return_value=_scheduled_task())), raising=False)
    events = MagicMock()
    queue = SimpleNamespace(add=AsyncMock(return_value={"status": "error", "msg": "Invalid URL"}))
    config = SimpleNamespace(default_preset="default")
    monkeypatch.setattr(EventBus, "get_instance", staticmethod(lambda: events))
    monkeypatch.setattr("app.library.config.Config.get_instance", staticmethod(lambda: config))
    monkeypatch.setattr(DownloadQueue, "get_instance", staticmethod(lambda: queue))

    await service._runner(_scheduled_task())

    queue.add.assert_awaited_once()
    emitted = [call.args[0] for call in events.emit.call_args_list]
    assert emitted == [Events.TASK_ERROR]


@pytest.mark.asyncio
async def test_runner_success(monkeypatch: pytest.MonkeyPatch) -> None:
    service = Tasks.__new__(Tasks)
    monkeypatch.setattr(service, "_repo", MagicMock(get=AsyncMock(return_value=_scheduled_task())), raising=False)
    events = MagicMock()
    queue = SimpleNamespace(add=AsyncMock(return_value={"status": "ok"}))
    config = SimpleNamespace(default_preset="default")
    monkeypatch.setattr(EventBus, "get_instance", staticmethod(lambda: events))
    monkeypatch.setattr("app.library.config.Config.get_instance", staticmethod(lambda: config))
    monkeypatch.setattr(DownloadQueue, "get_instance", staticmethod(lambda: queue))

    await service._runner(_scheduled_task())

    item = queue.add.await_args.kwargs["item"]
    assert item.extras["ignore_conditions"] == ["12", "Named"]
    emitted = [call.args[0] for call in events.emit.call_args_list]
    assert emitted == [Events.TASK_FINISHED]


@pytest.mark.asyncio
async def test_handler_ignores(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TaskHandle.__new__(TaskHandle)
    service._config = MagicMock(default_preset="default")
    service._queued = {}
    service._failure_count = {}
    queue = SimpleNamespace(
        queue=SimpleNamespace(exists=AsyncMock(return_value=False)),
        done=SimpleNamespace(get=AsyncMock(side_effect=KeyError)),
    )
    events = MagicMock()
    services = MagicMock()
    services.handle_async = AsyncMock(
        return_value=TaskResult(items=[TaskItem(url="https://example.com/video", archive_id="video 1")])
    )
    services.get.side_effect = lambda name: {"queue": queue, "notify": events}.get(name)
    monkeypatch.setattr(Services, "get_instance", staticmethod(lambda: services))

    handler = MagicMock(__name__="ExampleHandler")
    result = await service.dispatch(_task().model_copy(update={"preset": ""}), handler=handler)

    assert isinstance(result, TaskResult)
    payload = events.emit.call_args.kwargs["data"]
    assert payload["extras"]["ignore_conditions"] == ["12", "Named"]


@pytest.mark.asyncio
async def test_disabled_gallery_task_does_not_prevent_video_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(Config.get_instance(), "gallerydl_enabled", False)
    gallery = HandleTask(id=1, name="Gallery", url="https://vsco.co/fixture/gallery", engine="gallerydl", preset="")
    video = HandleTask(
        id=2,
        name="Video",
        url="https://example.com/video",
        engine="ytdlp",
        preset="",
        cli=f"--download-archive {tmp_path / 'archive.txt'}",
    )
    service = TaskHandle.__new__(TaskHandle)
    service._repo = MagicMock(all=AsyncMock(return_value=[gallery, video]))
    service._config = MagicMock(task_handler_random_delay=1.0)
    handler = type("VideoHandler", (), {})
    service._find_handler = AsyncMock(return_value=handler)
    service._dispatch = AsyncMock(return_value=TaskResult())

    await service._dispatcher()

    service._find_handler.assert_awaited_once_with(video)
    service._dispatch.assert_awaited_once_with(video, handler, delay=0.0)
