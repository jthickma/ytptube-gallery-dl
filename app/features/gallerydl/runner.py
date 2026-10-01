import collections
import logging
import os
import signal
import time
from pathlib import Path

from .opts import apply_options
from .utils import file_record


class GalleryOutput:
    """Gallery-dl downloader's native byte progress, without parsing terminal text."""

    def __init__(self, runner):
        self.runner = runner
        self.last = 0.0

    def start(self, path):
        self.runner.emit(status="downloading", msg=f"Downloading {Path(path).name}")

    def success(self, path):
        pass

    def skip(self, path):
        pass

    def progress(self, bytes_total, bytes_downloaded, bytes_per_second):
        self.runner.check_cancel()
        now = time.monotonic()
        if now - self.last < 0.5:
            return
        self.last = now
        self.runner.emit(
            status="downloading",
            downloaded_bytes=bytes_downloaded,
            total_bytes=bytes_total,
            speed=f"{bytes_per_second / 1024:.1f} KiB/s",
            eta=str(int((bytes_total - bytes_downloaded) / bytes_per_second))
            if bytes_total and bytes_per_second
            else None,
        )


class GalleryDLRunner:
    def __init__(self, item, params: dict, status_queue, logger=None, cancel_event=None):
        self.item = item
        self.params = params
        self.status_queue = status_queue
        self.logger = logger or logging.getLogger(__name__)
        self.cancel_event = cancel_event
        self.files: dict[str, dict] = {}
        self.directories: set[str] = set()
        self.partial_files: set[str] = set()
        self.skipped = 0
        self.completed = 0
        self.cancelled = False
        self.failure: str | None = None
        self.files.update({record["filename"]: record for record in getattr(item, "files", [])})

    def emit(self, **status):
        self.status_queue.put({"id": self.item._id, **status})

    def check_cancel(self):
        if self.cancelled or (self.cancel_event is not None and self.cancel_event.is_set()):
            # StopExtraction would be swallowed as a successful job. SystemExit
            # unwinds all child jobs and still runs their finalizers.
            raise SystemExit(130)

    def prepare(self, pathfmt):
        from gallery_dl import exception

        self.check_cancel()
        if (maximum := self.params.get("_max_items", 0)) and self.completed >= maximum:
            raise exception.StopExtraction
        self.directories.add(pathfmt.realdirectory)
        if pathfmt.temppath:
            self.partial_files.add(pathfmt.temppath)
        self.emit(status="downloading", downloaded_bytes=0, total_bytes=0, msg=f"Processing file {self.completed + 1}")

    def record(self, pathfmt):
        self.completed += 1
        record = file_record(pathfmt.path, self.item.download_dir, pathfmt.kwdict)
        if record:
            self.files[record["filename"]] = record
            self.emit(action="file", file=record)

    def skip(self, pathfmt):
        self.skipped += 1
        self.record(pathfmt)
        self.emit(
            status="downloading", msg=f"Skipped {self.skipped} archived/existing files", skipped_files=self.skipped
        )

    def error(self, pathfmt):
        self.failure = f"Failed to download {pathfmt.filename}"
        self.emit(status="downloading", msg=self.failure)

    def postprocessing(self, _pathfmt):
        self.emit(status="postprocessing")

    def run(self) -> int:
        from gallery_dl import job, output

        apply_options(self.params)
        runner = self

        class DownloadJob(job.DownloadJob):
            def initialize(self, kwdict=None):
                super().initialize(kwdict)
                runner.check_cancel()
                self.out = GalleryOutput(runner)
                if not isinstance(self.hooks, dict):
                    self.hooks = collections.defaultdict(list)
                self.register_hooks(
                    {
                        "prepare": runner.prepare,
                        "after": runner.record,
                        "skip": runner.skip,
                        "error": runner.error,
                        "file": runner.postprocessing,
                        "post-after": runner.postprocessing,
                    }
                )

            def handle_url(self, url, kwdict):
                runner.check_cancel()
                super().handle_url(url, kwdict)

            def handle_queue(self, url, kwdict):
                runner.check_cancel()
                super().handle_queue(url, kwdict)

            def download(self, url):
                try:
                    return super().download(url)
                finally:
                    pathfmt = self.pathfmt
                    if pathfmt is not None and pathfmt.temppath:
                        runner.partial_files.add(pathfmt.temppath)

        # initialize_logging defines upstream's TRACE logger method. It runs
        # only inside the worker, so no server logging state is mutated.
        output.initialize_logging(logging.WARNING)
        source = DownloadJob(self.item.url)
        self.emit(status="preparing")
        try:
            result = source.run()
            self.check_cancel()
            # ZIP/CBZ postprocessors can replace all original files during
            # finalization. Include the package produced for each touched folder.
            for directory in self.directories:
                for extension in (".zip", ".cbz"):
                    path = Path(directory.rstrip(os.sep) + extension)
                    if record := file_record(path, self.item.download_dir):
                        self.files[record["filename"]] = record
            files = [r for r in self.files.values() if (Path(self.item.download_dir) / r["filename"]).is_file()]
            self.emit(action="files", files=files, skipped_files=self.skipped)
            if result:
                self.emit(
                    status="error",
                    error=self.failure or f"Gallery-dl failed (status {result}).",
                    msg="Some files may have downloaded successfully.",
                )
            elif files:
                self.emit(status="finished", final_name=str(Path(self.item.download_dir) / files[0]["filename"]))
            else:
                self.emit(
                    status="skip",
                    download_skipped=True,
                    msg="No new files: the source is empty, filtered, or already archived.",
                )
            return result
        except SystemExit:
            self.emit(status="cancelled")
            # Only remove the active .part files touched by this job.
            for directory in self.directories:
                root = Path(self.item.download_dir).resolve()
                folder = Path(directory).resolve()
                if folder.is_relative_to(root):
                    for part in folder.glob("*.part"):
                        if str(part) in self.partial_files and not part.is_symlink():
                            part.unlink(missing_ok=True)
            root = Path(self.item.download_dir).resolve()
            for filename in self.partial_files:
                path = Path(filename)
                if path.name.endswith(".part") and path.resolve().is_relative_to(root) and not path.is_symlink():
                    path.unlink(missing_ok=True)
            return 130

    def install_cancel_handler(self):
        if hasattr(signal, "SIGUSR1"):

            def mark_cancelled(*_):
                self.cancelled = True

            signal.signal(signal.SIGUSR1, mark_cancelled)
