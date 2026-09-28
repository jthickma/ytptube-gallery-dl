# Plan: Full `gallery-dl` module support in YTPTube

> Target repository: `jthickma/ytptube-gallery-dl` (fork of `ArabCoders/ytptube`, branch `dev`).
> Goal: add `gallery-dl` as a first-class download engine alongside `yt-dlp`, so image posts,
> image galleries/collections, and video URLs supported by `gallery-dl` can be queued,
> downloaded, tracked in history, archived, and browsed from the same UI/API.

---

## 1. Objective and scope

### 1.1 What "full gallery-dl support" means here

YTPTube today is a `yt-dlp`-only download manager. The task is to make `gallery-dl`
a peer engine that handles three URL classes that `yt-dlp` handles poorly or not at all:

1. **Single media/image URLs** — direct image hosts, single post URLs, single images
   inside a gallery site, and `gallery-dl`'s `directlink`/imagehost extractors.
2. **Galleries / collections** — user profiles, tag searches, artist pages, albums,
   manga chapters, saved/liked lists (multi-file, multi-post sources).
3. **Video URLs** — sites where `gallery-dl` has a better or only extractor, and
   `gallery-dl`'s own `ytdl` integration (the `gallery-dl[video]` extra wires in `yt-dlp`).

### 1.2 In scope

- A new backend feature module `app/features/gallerydl/` (runner, extractor, options,
  archive/metadata helpers, routes, tests).
- An `engine` concept on queue items, presets, and task definitions, with an
  `auto` mode that routes URLs by capability detection.
- Integration into the existing download runtime (subprocess, status queue, progress,
  cancellation, archive, history) so gallery downloads behave like video downloads.
- Multi-file gallery items (a "gallery" that produces an ordered list of files).
- Scheduler/task support (recurring gallery sources).
- API + UI surface (options, engine selector, gallery rendering in history/library).
- Config/env vars, dependency installation, update checking, documentation.

### 1.3 Non-goals (for the first delivery)

- Replacing `yt-dlp` for video. `gallery-dl` is additive; `yt-dlp` remains the default.
- Implementing every `gallery-dl` CLI flag on day one. The engine supports the
  app-relevant option set plus raw `-o key=value` passthrough; a documented escape
  hatch covers the rest.
- External downloader/aria2 orchestration for gallery files beyond what `gallery-dl`
  already offers natively.

---

## 2. Current architecture (as-is)

This section records the facts the plan is built on, with the exact files involved.

### 2.1 Application bootstrap

- `app/main.py` (`Main.start`) instantiates singletons and calls `.attach(app)`,
  which both wires lifecycle hooks and registers the service:
  `SqliteStore`, `DownloadsRepository`, `AuthService`, `Scheduler`, `Cache`,
  `TerminalSessionManager`, `HttpSocket`, `HttpAPI`, `Tasks`, `Notifications`,
  `Conditions`, `DLFields`, `TaskDefinitionsRepository`, `ExtractorPool`,
  `DownloadQueue`, `UpdateChecker`, `ResourceTracker`.
- `HttpAPI.add_routes()` discovers HTTP routes by importing every module under
  `app/routes/api/` (`load_modules`) and collecting `@route(...)`-decorated handlers.
  Feature routers live in `app/features/<feature>/router.py` and are pulled in by a
  one-line shim in `app/routes/api/<feature>.py` (e.g. `app/routes/api/yt_dlp.py`).
- `Config` (`app/library/config.py`) is a singleton whose class attributes become
  `YTP_*` env vars automatically. Adding a new config option = add a typed class
  attribute (+ register it in `_int_vars`/`_boolean_vars`/`_float_vars` if needed).

### 2.2 Queue item model

- `app/features/downloads/items.py`
  - `Item` — user-supplied request: `url, preset, folder, cookies, template, cli,
    extras, requeued, auto_start, force_start`. `get_ytdlp_opts()` merges preset +
    CLI + item options through `YTDLPOpts`.
  - `ItemDTO` — the runtime/history record. Key fields: `_id, id, title, url, preset,
    folder, download_dir, temp_dir, status, cookies, template, template_chapter,
    is_live, file_size, options, extras, cli, auto_start, force_start, filename,
    downloaded_bytes, total_bytes, speed, percent, archive_id, is_archivable,
    is_archived, download_skipped, sidecar`.
  - `ItemDTO.serialize()` → stored as JSON (`DownloadModel.data`) in the `history`
    table (`app/features/downloads/models.py`). Extra fields are therefore
    **backward compatible** (new JSON keys just appear on new records).

### 2.3 Download runtime (the important part)

`app/features/downloads/runtime/`:

- `queue_manager.py` → `DownloadQueue` singleton. Owns `queue` and `done` `DataStore`s,
  the `PoolManager`, scheduler jobs (`check_for_stale`, `check_live`, `check_retries`,
  `cleanup_thumbnails`, `delete_old_history`), and the public add/cancel/clear APIs.
  `DownloadQueue.add()` delegates to `item_adder.add`.
- `item_adder.py` → `add()` extracts info (via `app/features/ytdlp/extractor.py`
  `fetch_info`, which runs `YTDLP.extract_info` in a process pool), runs
  conditions, archive checks, then `add_item()` routes by `entry["_type"]`:
  `playlist*` → `playlist_processor.process_playlist`;
  `video`/`url_transparent` → `video_processor.add_video`;
  `url*` → recursive `add`.
- `video_processor.py` → builds an `ItemDTO` and a `Download(info=..., info_dict=...)`,
  then `queue.queue.put()` + `pool.trigger_download()`.
- `playlist_processor.py` → iterates `entry["entries"]` and calls `queue.add` per entry.
- `pool_manager.py` → `PoolManager._download_pool()` selects queued `Download`s
  (skips `started`/`cancelled`/`auto_start=False`), enforces global `max_workers`
  and per-extractor semaphores keyed by `entry.info.get_extractor()`, then
  `_download_file()` calls `entry.start()` and moves the item to history.
- `core.py` → `Download`. `start()` creates the `status_queue`, `StatusTracker`,
  `HookHandlers`, then `ProcessManager.create_process(target=self._download)` and
  `start()`. `_download()` runs inside the child `multiprocessing.Process`:
  builds yt-dlp params, creates cookie file, extracts info if needed, constructs
  `YTDLP(params)` and calls `download()`/`process_ie_result()`, and pushes
  status dicts onto `status_queue`.
- `hooks.py` → `HookHandlers.progress_hook/postprocessor_hook/post_hook` translate
  yt-dlp callbacks into status-queue dicts filtered by `YTDLP_PROGRESS_FIELDS`.
- `status_tracker.py` → `StatusTracker.progress_update()` consumes the queue and
  updates the `ItemDTO`; `_finalize_file()` sets `filename`, `file_size`, runs
  `ffprobe`, sets `extras.is_video/is_audio/media_profile`, then marks `final_update`.
  `final_name` from `post_hook` triggers finalization and `status="finished"`.
- `process_manager.py` → owns the child process, sends `SIGUSR1` (POSIX) for
  graceful cancel, escalates to `terminate()`/`kill()`.
- `utils.py` → `GENERIC_EXTRACTORS`, `YTDLP_PROGRESS_FIELDS`,
  `get_extractor_limit()` (creates `YTP_MAX_WORKERS_FOR_<EXTRACTOR>`-aware semaphores).

### 2.4 yt-dlp wrapper

- `app/features/ytdlp/ytdlp.py` → `YTDLP(yt_dlp.YoutubeDL)` registers bundled plugins,
  custom outtmpl handling, and an `Archiver`-backed `download_archive` proxy.
- `app/features/ytdlp/utils.py` → `_DATA.YTDLP_PARAMS` (simulate defaults),
  `arg_converter`, `get_archive_id(url)`, `get_extras(entry)`, `ytdlp_reject`,
  `archive_add/archive_read`.
- `app/features/ytdlp/archiver.py` → global, cached, thread-safe archive file reader/writer.

### 2.5 Tasks, presets, conditions

- `app/features/tasks/definitions/service.py` → `TaskHandle` auto-discovers handlers from
  `app/features/tasks/definitions/handlers/` (`pkgutil`) by testing `can_handle(task)`.
- Handlers implement `can_handle`, `extract`/`inspect`, `parse`, `tests`
  (`_base_handler.BaseHandler`).
- `app/features/tasks/schemas.py` → `Task` fields: `name, url, folder, preset, timer,
  template, cli, ignore_conditions, auto_start, handler_enabled, enabled`.
- `app/features/presets/schemas.py` → `Preset` fields: `name, description, folder,
  template, cookies, cli, default, priority`; `cli` is validated by the yt-dlp parser.
- `app/features/presets/defaults.py` → seeded default presets.
- `app/features/presets/ytdlp_opts.py` (`YTDLPOpts`) → precedence: user CLI > preset CLI
  > item opts > preset opts > defaults; `arg_converter` turns CLI strings into dicts.

### 2.6 Installer / updates

- `app/library/PackageInstaller.py` → `pip install` for `YTP_PIP_PACKAGES`; special
  handling for `yt_dlp` (stable/master/nightly channels, GitHub release lookup).
- `app/library/UpdateChecker.py` → checks app + yt-dlp GitHub releases; sets
  `config.new_version` / `config.yt_new_version`.
- `pyproject.toml` uses `uv`; `Dockerfile` builds with `uv sync` and bundles a
  `yt-dlp` standalone binary at `/opt/bin/yt-dlp`.

### 2.7 gallery-dl facts (pinned to verify at implementation time)

- PyPI `gallery-dl` (module `gallery_dl`), currently **1.32.14**, `requires-python>=3.8`,
  runtime dep `requests`; the `[video]`/`[extra]` extras pull `yt-dlp`, `jinja2`,
  `pyyaml`, `toml`, etc.
- Programmatic API (verified against 1.32.14 source):
  - `gallery_dl.extractor.find(url)` → extractor instance or `None`
    (`extractor.extractors()` enumerates all classes; `.category`, `.subcategory`,
    `.basecategory`, `.pattern`).
  - `gallery_dl.job.DownloadJob(url)` / `SimulationJob` / `DataJob` / `UrlJob` /
    `KeywordJob` / `InfoJob`; `job.run()` returns a status bitmask.
  - `job.register_hooks({event: callback})` with events: `init, prepare,
    prepare-after, file, after, post, post-after, error, skip, child, child-after,
    finalize, finalize-success, finalize-error`. Callbacks receive `pathfmt`
    (`pathfmt.filename`, `pathfmt.path`, `pathfmt.temppath`, `pathfmt.kwdict`, …).
  - `gallery_dl.config.set(path_tuple, key, value)`, `config.load(files)`,
    `config.setdefault`, `config.clear`.
  - Message model: `Message.Directory/Url/Queue` tuples yielded by extractors.
  - CLI options (documented) include `--download-archive`, `--cookies`,
    `--cookies-from-browser`, `--range/--post-range/--child-range`,
    `--filter/--post-filter/--child-filter`, `--filesize-min/max`,
    `--date-before/after`, `--sleep`, `--retries`, `--http-timeout`, `--proxy`,
    `--limit-rate`, `--write-metadata`, `--write-info-json`, `--write-tags`,
    `--zip`, `--cbz`, `--ugoira`, `-P/--postprocessor`, `-o/--option`,
    `-j/--dump-json`, `-J/--resolve-json`, `-g/--get-urls`, `-s/--simulate`.

---

## 3. Design overview

### 3.1 Core idea: an "engine" abstraction

Introduce an `engine` discriminator that flows through the same places `preset`
flows today:

- `engine = "auto"` (default) → decide per URL by capability detection.
- `engine = "ytdlp"` → force `yt-dlp` (today's behavior).
- `engine = "gallerydl"` → force `gallery-dl`.

The `Download` runtime keeps a single subprocess/status-queue/cancel/journaling
model; only the middle (`_download`) branches on engine. This preserves all the
existing hardening (process management, stale detection, live handling, history).

```
Item(url, engine) ──► DownloadQueue.add ──► item_adder
                                              │
                          ┌───────────────────┴────────────────────┐
                          ▼ engine=ytdlp/auto(gallery-dl wins)     ▼
                  yt-dlp extractor (fetch_info)            gallery-dl extractor
                          │                                        │
                  entry(_type=video/playlist)             entries (posts/files)
                          ▼                                        ▼
                  video/playlist_processor               gallery_processor
                          └──────────────► ItemDTO + Download ◄────┘
                                              │
                                         PoolManager
                                              │
                              Download.start → subprocess → _download
                                              │  engine branch
                                       YTDLP(...)      GalleryDLRunner(...)
                                              │
                                        status_queue → StatusTracker → history
```

### 3.2 Engine selection / detection

Add `app/features/gallerydl/detect.py` (or `extractor.py`):

- `gallerydl_matches(url) -> bool` — `gallery_dl.extractor.find(url) is not None`.
- `ytdlp_matches(url) -> bool` — reuse `get_archive_id(url)` from
  `app/features/ytdlp/utils.py` (returns `ie_key` when a yt-dlp extractor is suitable).
- Resolution rules for `auto`:
  1. If only one engine matches → use it.
  2. If both match → prefer `yt-dlp` by default (video-first), **unless** the URL is
     classified as image/gallery (see override list) or the user/preset/task set
     `engine_preference=gallerydl`.
  3. If neither matches → fall back to `yt-dlp` `generic` extractor (today's behavior),
     and surface a clear message.
- Detection is cheap (regex `.pattern.match`) and runs in `item_adder.add` before
  extraction; cache results with `timed_lru_cache` like `get_archive_id` does.
- Configurable override lists:
  - `YTP_GALLERYDL_SITES` — comma-separated extractor categories that always win.
  - `YTP_GALLERYDL_EXCLUDE_SITES` — categories never auto-selected.

### 3.3 Execution model

**Decision: run `gallery-dl` in-process as a library inside the existing download
subprocess, using its `job` + `config` + `hooks` API.** Rationale:

- The download already executes in a dedicated `multiprocessing.Process` (`core._download`),
  so importing/using `gallery_dl` there is isolated from the server loop — same model
  as `yt_dlp`.
- Library mode gives direct access to `register_hooks` for accurate per-file progress,
  skip/error events, and clean cancellation, without parsing stdout.
- It avoids re-spawning an interpreter per file/post.

**Fallback / escape hatch:** an opt-in passthrough mode that shells out to
`python -m gallery_dl <raw args>` for users who need an exotic flag that the mapper
does not yet cover (`YTP_GALLERYDL_CLI_PASSTHROUGH=true`, per-item override via
`extras.gallerydl_passthrough`). The subprocess path streams stdout/stderr into the
status queue. This guarantees "full module support" without blocking on mapping every
flag.

### 3.4 Option mapping (app concept → gallery-dl config)

A curated mapping is applied with `config.set(path, key, value)` (and `-o` passthrough),
plus explicit file/dir/path handling. Initial mapping:

| YTPTube concept | gallery-dl config key (`config.set` path) | Notes |
|---|---|---|
| download base dir | `("extractor",) base-directory` | from `config.download_path` + folder |
| folder | `("extractor",) directory` | `[<folder>]` or `()` |
| output template | `("extractor",) filename` | gallery-dl uses `{field}` syntax — see §5.4 |
| cookies | `("extractor",) cookies` | write Netscape cookies via `create_cookies_file` |
| archive | `("extractor",) archive` / `--download-archive` | separate gallery-dl archive (§7) |
| template_chapter | n/a | chapters not modeled; ignore |
| proxy | `("extractor",) proxy` | from yt-dlp opts |
| timeout | `("extractor",) timeout` / `("downloader",) timeout` | from opts |
| retries | `("extractor",) retries` | |
| rate limit | `("downloader",) rate` | |
| sleep | `("downloader",) sleep`, `("extractor",) sleep` | |
| filters | `("extractor",) filter`, `post-filter`, `child-filter` | |
| range | `("extractor",) range`, `post-range`, `child-range` | |
| filesize | `("downloader",) filesize-min/max` | |
| date bounds | `("extractor",) date-before/date-after` | |
| postprocessors | `("extractor",) postprocessors` | list, e.g. metadata, ugoira |
| write metadata | `("extractor",) "write-metadata"` / `"write-info-json"` | |
| passthrough | `-o key=value` pairs parsed into `config.set` | |
| verbose/debug | `("output",) mode` / log level | |

Because gallery-dl option validation is engine-specific, `YTDLPOpts` will **not** be
used for gallery-dl. A separate `GalleryDLOpts` builder (mirroring `YTDLPOpts`
precedence: item > preset > defaults) will produce a plain dict consumed by the runner.

---

## 4. Repository layout changes

### 4.1 New files

```
app/features/gallerydl/
├── __init__.py
├── runner.py          # in-process library runner used inside the download subprocess
├── extractor.py       # detection + simulate/metadata extraction (queue expansion)
├── opts.py            # GalleryDLOpts: app settings/CLI -> gallery_dl config dict
├── utils.py           # archive-id synthesis, category naming, cookie/path helpers
├── router.py          # @route endpoints (options, extractors, convert)
└── tests/
    ├── __init__.py
    ├── test_gallerydl_detect.py
    ├── test_gallerydl_opts.py
    ├── test_gallerydl_runner.py
    └── test_gallerydl_router.py

app/routes/api/gallery_dl.py          # shim: import app.features.gallerydl.router
app/features/downloads/runtime/gallery_processor.py
app/features/tasks/definitions/handlers/gallerydl.py
app/features/gallerydl/tests/...      # (as above)
```

### 4.2 Modified files (backend)

```
app/features/downloads/items.py              # engine field; gallery multi-file fields
app/features/downloads/runtime/core.py       # branch _download by engine
app/features/downloads/runtime/item_adder.py # detection + gallery extraction + routing
app/features/downloads/runtime/status_tracker.py  # multi-file finalization
app/features/downloads/runtime/pool_manager.py    # engine-aware extractor label
app/features/downloads/runtime/queue_manager.py   # gallery folder file removal
app/features/downloads/runtime/utils.py       # gallery progress fields / constants
app/features/presets/schemas.py, defaults.py, router.py, service.py  # engine-aware presets
app/features/tasks/schemas.py, defs/schemas.py, defs/results.py      # engine-aware tasks
app/library/config.py                        # new YTP_GALLERYDL_* settings
app/library/PackageInstaller.py              # install/upgrade gallery-dl
app/library/UpdateChecker.py                 # gallery-dl release check
app/main.py                                  # (optional) init/registration
pyproject.toml                               # add gallery-dl dependency
uv.lock                                       # regenerated
Dockerfile / compose.yaml                    # install gallery-dl (+[video]) in image
```

### 4.3 Modified files (frontend/docs)

```
ui/app/components/NewDownload.vue            # engine selector
ui/app/components/YTDLPOptions.vue           # engine-aware options / gallery-dl options
ui/app/components/PresetForm.vue             # engine field + gallery-dl options
ui/app/components/TaskForm.vue               # engine field
ui/app/components/ImageView.vue / PlaylistEntryList.vue  # gallery rendering
ui/app/pages/history.vue, simple.vue         # gallery badge / file list
ui/app/types/*.d.ts, ui/i18n/locales/*.json  # types + translations
API.md, docs/features.md, FAQ.md, README.md  # docs
```

---

## 5. Data model changes

### 5.1 `Item` (request)

Add:

```python
engine: str = "auto"          # "auto" | "ytdlp" | "gallerydl"
```

- Parse in `Item.format()` (validate against the allowed set).
- Serialize automatically via `__dict__`.
- `new_with()` already spreads `serialize()`, so it carries through.

### 5.2 `ItemDTO` (runtime/history)

Add engine + gallery fields:

```python
engine: str = "ytdlp"            # resolved engine actually used
gallerydl: dict = field(default_factory=dict)   # category/subcategory/post id etc.
files: list[dict] = field(default_factory=list) # [{"filename":..., "size":..., "mime":...}]
is_gallery: bool = False
gallery_count: int | None = None
```

- Add to `ItemDTO.removed_fields()` only if superseded later; new fields are additive.
- `files` is appended by the runner via status events; `filename` remains the
  **primary/first** file for backward-compatible playback/thumbnails.
- `extras` can also hold `gallerydl_category`, `post_url`, `post_id`, `tags`, etc.,
  but first-class fields keep the UI simple.

Stored history JSON gains these keys automatically. Old records load with defaults
via `init_class(ItemDTO, item_data, item_fields)` in `DownloadModel.to_item()`.

### 5.3 Archive

- Introduce a gallery-dl-native archive file, e.g. `config.config_path/gallerydl-archive.sqlite3`
  or `<download_path>/.gallery-dl/archive.sqlite3`, passed as `archive` config.
- Separately, synthesize a YTPTube-facing archive id for history/UI:
  `gallerydl <category>:<subcategory>:<post_id>` (or `gallerydl <category>:<id>`),
  computed from the extractor + `kwdict`. Used for `is_archivable/is_archived`
  badges and duplicate detection in `add()`.
- `get_archive_id(url)` stays yt-dlp-only; add `gallerydl_archive_id(url, kwdict)`.
- Archive writes go through the existing `Archiver` only for the YTPTube-facing id;
  the native gallery-dl archive is written by gallery-dl itself (its format differs).

### 5.4 Output template

Two template dialects exist:

- yt-dlp: `%(title)s.%(ext)s`
- gallery-dl: `{category}_{id}_{num:>02}.{extension}`

Plan:
- Keep the existing yt-dlp `template` semantics for `engine=ytdlp`.
- For `engine=gallerydl`, treat `GalleryDLOpts.filename` as a gallery-dl format string.
  Default from config: `YTP_GALLERYDL_FILENAME` (e.g.
  `"{category}_{id}_{num:>02}.{extension}"`).
- In the UI, the template field switches dialect/placeholder help based on `engine`.
- `folder` maps to gallery-dl `directory`; `base-directory` is the download root.

---

## 6. Backend implementation detail

### 6.1 `app/features/gallerydl/opts.py` — `GalleryDLOpts`

Mirror `YTDLPOpts` precedence but for gallery-dl:

```python
class GalleryDLOpts:
    @classmethod
    def get_instance(cls) -> "GalleryDLOpts": ...
    def add_raw(self, args: str) -> "GalleryDLOpts": ...      # -o key=value / config JSON
    def preset(self, name: str) -> "GalleryDLOpts": ...       # engine-aware preset
    def add(self, config: dict) -> "GalleryDLOpts": ...
    def get_all(self) -> dict: ...                            # -> gallery_dl config dict
```

Responsibilities:

- Validate raw options (whitelist of config keys, or accept `-o key=value` only).
- Resolve `base-directory`, `directory`, `filename`, `archive`, `cookies`.
- Translate `%`-style replacements from `config.get_replacers()` only where meaningful.

### 6.2 `app/features/gallerydl/extractor.py` — detection + enumeration

Two entry points:

1. `detect(url) -> EngineInfo` — cheap capability detection (§3.2) used by `item_adder`.
2. `async extract(url, opts) -> GalleryExtract` — run a `SimulationJob`/`DataJob`
   (in the extractor process pool, reusing `ExtractorPool`/`ExtractorBatch`) to get
   the list of **messages** without downloading. Used to:
   - decide whether the URL is a single item or a collection (expansion),
   - build `ItemDTO` metadata (title, post id, tags, thumbnail),
   - synthesize archive ids,
   - return `Message.Queue` child URLs for per-post expansion.

`extract` must run off the event loop; reuse the existing
`ExtractorPool`/`ProcessPoolExecutor` machinery (picklable config dicts only).

### 6.3 `app/features/gallerydl/runner.py` — the actual download

Runs inside `Download._download` for `engine=gallerydl`.

```python
class GalleryDLRunner:
    def __init__(self, item: ItemDTO, params: dict, hooks: GalleryHooks, logger): ...
    def run(self) -> int:
        # 1. apply options -> gallery_dl.config
        # 2. build job = DownloadJob(item.url)
        #    (or DataJob/UrlJob for enumerate-only modes)
        # 3. job.register_hooks(self.hooks.to_gallery_hooks())
        # 4. return job.run()
```

`GalleryHooks` maps gallery-dl hook events to the existing status-queue protocol
(`hooks.py`/`status_tracker.py`):

| gallery-dl event | status-queue update |
|---|---|
| `init` | `{"status": "preparing"}` |
| `prepare` (per file) | `{"status":"downloading","filename":..., "downloaded_bytes":0,"total_bytes":<http size>}` |
| `file` | append file to `files`, set `filename` if first |
| `after` (per file) | `{"downloaded_bytes":size,"total_bytes":size}` + maybe per-file finalize event |
| `skip` | increment skip counter; emit `{"status":"downloading","msg":"skipped ..."}` |
| `error` | collect message (fed to `NestedLogger.failure_message`) |
| `post` / `post-after` | `{"status":"postprocessing"}` |
| `finalize` | `{"status":"finished","final_name": <primary file abs path>}` |

Multi-file handling: because `StatusTracker` finalizes a single file, extend it with a
new status action `"file"` that appends to `info.files` **without** ending the item,
and only emit `final_name` once at `finalize` (the primary file). This keeps the
existing single-file finalization path working while recording all files.

Cancellation: `ProcessManager` already signals the child (SIGUSR1 POSIX). Install a
handler in `_download` (gallery-dl path) that calls the job's stop/abort mechanism
(raise `gallery_dl.exception.StopExtraction` from a hook, or set a cancel flag checked
in `prepare`) so partial files are cleaned up. Fall back to `terminate()`/`kill()`
via the existing escalation if needed.

### 6.4 `app/features/downloads/runtime/gallery_processor.py`

Analogous to `playlist_processor.py`. Given an extracted gallery result:

- If the result is a **collection with child URLs** (`Message.Queue`) and expansion is
  enabled → for each child URL call `queue.add(Item(url=child, engine="gallerydl", ...))`
  with playlist-like `extras` (parent title/id, index, count). This reuses the
  playlist machinery and gives one history row per post.
- Otherwise (single post / direct image / single video) → build one `ItemDTO` and a
  `Download(info=..., info_dict=None)` and `queue.queue.put()`.
- `extras.gallery_count`, `extras.gallery_mode` (`"item"` | `"expand"`) recorded.
- Respect a `max_downloads`-style bound (`--range`/`YTP_GALLERYDL_MAX_ITEMS`).

### 6.5 `item_adder.py` integration

In `add()` (after preset resolution, before `yt_conf` usage):

1. Resolve engine: explicit `item.engine`, else preset/task `engine`, else
   `detect(item.url)`.
2. If `engine == "gallerydl"`:
   - Build `GalleryDLOpts` (not `YTDLPOpts`).
   - Archive check using `gallerydl_archive_id`.
   - `await gallery_extractor.extract(...)` for metadata/enumeration.
   - Route to `gallery_processor`.
   - Conditions still apply on extracted metadata (keep `Conditions.match`).
3. Else, today's yt-dlp path unchanged.

Guard all existing yt-dlp-specific calls (`_is_youtube`, `_extract_config`,
`ytdlp_reject`, archive-id checks) behind the engine branch.

### 6.6 `core.py` integration

In `Download.__init__`, resolve `self.engine` from `info.engine`. In `_download()`:

```python
if self.engine == "gallerydl":
    self._download_gallerydl()   # GalleryDLRunner + GalleryHooks
else:
    self._download_ytdlp()       # existing body
```

- Extract the existing body into `_download_ytdlp` (pure move, no behavior change).
- `_download_gallerydl`:
  - builds params via `GalleryDLOpts`,
  - applies `config` (paths/archive/cookies),
  - constructs `GalleryDLRunner`,
  - installs cancel handling,
  - pushes `{"status":"downloading"}` then `finished`/`error` with the same schema,
  - cleans up the cookie file in `finally` (mirror existing logic).
- `is_live` should be `False` for gallery-dl items (no live semantics); ensure
  `BAD_LIVE_STREAM_OPTIONS`/live branches are skipped.

### 6.7 `pool_manager.py` / `utils.py` integration

- `entry.info.get_extractor()` for gallery-dl should return a stable label, e.g.
  `gallerydl:<category>` (from `extras.gallerydl_category`), so per-extractor worker
  limits work and `YTP_MAX_WORKERS_FOR_GALLERYDL_<CATEGORY>` is honored.
- Add gallery progress fields (`filename`, `downloaded_bytes`, `total_bytes`, `speed`,
  `eta`, `files`) to `YTDLP_PROGRESS_FIELDS` (or a parallel tuple) so hooks pass them
  through.

### 6.8 History / file removal

- `queue_manager.clear()` / `clear_bulk()` currently remove `glob(stem.*)` next to a
  single file. For gallery items:
  - if `info.is_gallery` and `info.files` → delete each recorded file (and its
    sidecars/thumbnails), or the item folder if it is exclusively owned.
  - Keep a conservative guard: never delete a shared collection folder unless
    `YTP_GALLERYDL_DELETE_FOLDER=true`.
- `_finalize_file()` in `StatusTracker` runs ffprobe per file; for images consider
  skipping ffprobe (or running it only on video/audio files) to avoid overhead, and
  set `extras.is_image` based on mime/extension. Reuse `app/routes/api/_static.py`
  `EXT_TO_MIME` for classification.

### 6.9 Library/player side

- History thumbnails: `app/routes/api/history.py` `item_view`/`thumbnail` assume a
  single media file. For galleries, expose the first image as the thumbnail and the
  full `files` list for the detail view.
- `ImageView.vue` already renders images; add a gallery grid component
  (new `GalleryView.vue`) or extend `PlaylistEntryList.vue` to list `files`.
- The browser (`app/routes/api/browser.py`) already browses arbitrary files, so
  gallery folders are browsable without changes.

---

## 7. Configuration and environment variables

Add to `Config` (all `YTP_`-prefixed automatically):

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `YTP_GALLERYDL_ENABLED` | bool | `true` | master switch |
| `YTP_GALLERYDL_AUTO` | bool | `true` | allow auto-detection |
| `YTP_GALLERYDL_SITES` | str | `""` | categories that win auto-detect |
| `YTP_GALLERYDL_EXCLUDE_SITES` | str | `""` | categories never auto-selected |
| `YTP_GALLERYDL_FILENAME` | str | `{category}_{id}_{num:>02}.{extension}` | default filename format |
| `YTP_GALLERYDL_ARCHIVE` | str | `""` | native archive path (default under config) |
| `YTP_GALLERYDL_MAX_ITEMS` | int | `0` | cap expanded posts (0 = unlimited) |
| `YTP_GALLERYDL_CLI_PASSTHROUGH` | bool | `false` | use CLI subprocess escape hatch |
| `YTP_GALLERYDL_CONFIG` | str | `""` | extra gallery-dl config file to `config.load` |
| `YTP_GALLERYDL_TMP_USE` | bool | `false` | use temp dir for `.part` files |
| `YTP_GALLERYDL_DELETE_FOLDER` | bool | `false` | delete owned gallery folders on clear |
| `YTP_GALLERYDL_PIP_PACKAGE` | str | `gallery-dl` | package spec (allows extras/pins) |

Register bool/int vars in `Config._boolean_vars` / `_int_vars`; add
`engine`-related fields to `_frontend_vars` so the UI knows the engine is available.

---

## 8. Presets and CLI options

### 8.1 Preset changes

- `Preset` gains `engine: str = "auto"` and a gallery-dl options field. Two options:
  - **Reuse `cli`** and validate with the gallery-dl parser when `engine=gallerydl`
    (recommended for minimal schema churn), or
  - Add `gallerydl: str = ""` to hold gallery-dl options.
- The plan recommends adding a dedicated `gallerydl` field on `Preset`/`Item`/`Task`
  to avoid mixing dialects, **while also accepting** gallery-dl options via `cli`
  when `engine=gallerydl` for terse cases.
- `Preset._validate_cli` must branch on engine and skip yt-dlp `arg_converter` for
  gallery-dl presets.
- Seed new default presets (`app/features/presets/defaults.py`):
  - `gallery_images` — images only, `--filesize-min`, metadata write, no video.
  - `gallery_full` — full gallery, `--download-archive`, `--write-metadata`.
  - `gallery_video` — engine `gallerydl` with `ytdl`-backed video postprocessing.

### 8.2 Validation

- Add a `gallerydl_arg_converter(args) -> dict` (or config keys whitelist) in
  `app/features/gallerydl/opts.py`, used by `Preset`, `Item.format`, and task schemas.
- Support `-o key=value` and JSON config to cover arbitrary options without schema churn.

---

## 9. Tasks / scheduler support

- New handler `app/features/tasks/definitions/handlers/gallerydl.py`:
  - `can_handle(task)` → `task.engine == "gallerydl"` or
    `detect(task.url).engine == "gallerydl"` (respect explicit engine).
  - `extract(task)` → run `gallery_dl` in **simulate/enumerate** mode, compute archive
    ids, filter out archived entries (using the native gallery-dl archive plus the
    YTPTube-facing id), then dispatch via `DownloadQueue` with `extras.source_handler="web"`
    and `source_id`/`source_name` (mirrors `generic.py`/`rss.py`).
  - `inspect(task)` → return candidate items for the UI (`TaskInspect.vue`).
  - `tests()` → include a handful of well-known gallery URLs, gated/skipped in CI.
- `Task`/`HandleTask` gain `engine` and pass it through `get_ytdlp_opts`-equivalent
  (`get_gallery_opts`).
- `TaskDefinitionsRepository`/migrations: no column changes required if `engine`
  lives in the task JSON/`TaskModel` columns already; if `tasks`/`task_definitions`
  tables store structured columns, add an `engine` column + migration
  (`app/migrations/<ts>_add_task_engine.py`) — verify at implementation time.

---

## 10. API surface

New endpoints (module `app/features/gallerydl/router.py`, shim
`app/routes/api/gallery_dl.py`), following existing conventions
(`api_error_response`, auth defaults, `@route`):

- `GET api/gallery-dl/options/` → supported option schema (mirrors
  `api/yt-dlp/options/`), for the UI options editor.
- `GET api/gallery-dl/extractors/` → list of extractor categories/subcategories
  (`gallery_dl.extractor.extractors()`), for autocomplete and site allowlists.
- `POST api/gallery-dl/convert/` → validate/translate raw gallery-dl options into a
  config dict (mirrors `api/yt-dlp/convert/`).
- `GET api/gallery-dl/url/info/` → enumerate a URL (simulate) for the
  "Get Info" / inspect UI.
- `POST api/gallery-dl/version/` (optional) → installed version + update status.

Existing endpoints that need engine propagation (no new routes, just fields):

- `POST api/history/` (add) — accept `engine`/`gallerydl` fields on the item.
- `GET api/history/{id}` — return `files`, `is_gallery`, `engine`.
- `api/presets/*`, `api/task_definitions/*`, `api/tasks/*` — accept `engine`.

`API.md` must document all of the above.

---

## 11. Frontend work

- `NewDownload.vue`: add an engine selector (`Auto` / `yt-dlp` / `gallery-dl`);
  show gallery-dl template dialect help; gate yt-dlp-only fields (format, chapters,
  subtitles) when `engine=gallerydl`.
- `YTDLPOptions.vue`: render gallery-dl options when engine is gallery-dl (fetch from
  `api/gallery-dl/options/`); or split into `GalleryDLOptions.vue`.
- `PresetForm.vue` / `TaskForm.vue`: engine field + gallery-dl option editor.
- `history.vue` / `simple.vue`: gallery badge, file count, gallery-aware thumbnails.
- New `GalleryView.vue` (grid/lightbox) or extend `ImageView.vue` /
  `PlaylistEntryList.vue` to display `files`.
- `ui/app/types/*.d.ts`: add `engine`, `files`, `is_gallery`, `gallery_count`.
- `ui/i18n/locales/*.json`: new strings (en, ar, fr, ja, zh).
- `useYtpConfig.ts`: expose `gallerydl_enabled`, engine availability.

---

## 12. Dependency, installer, and update integration

- `pyproject.toml`: add `gallery-dl>=1.32,<2` (optionally `gallery-dl[video]` to enable
  `ytdl`-based video postprocessing; note it pulls `yt-dlp`, already present).
- Regenerate `uv.lock`.
- `Dockerfile`: `uv sync` picks it up from `pyproject.toml`; if the `[video]` extra is
  used, ensure `ffmpeg`/`mkvtoolnix` are present (already installed).
- `app/library/PackageInstaller.py`: extend to install/upgrade `gallery_dl` like
  `yt_dlp`, including a channel spec (`stable`/pinned). Add to the allowed package set.
- `app/library/UpdateChecker.py`: add `_check_gallerydl_version` against the gallery-dl
  releases (Codeberg/GitHub mirror) and expose `config.gallerydl_new_version`; surface
  in diagnostics and the changelog UI.
- `app/library/diagnostics.py`: report gallery-dl presence/version.

---

## 13. Migrations and backward compatibility

- No schema change is strictly required because queue/history items and task
  definitions are stored as JSON. Verify `tasks`/`task_definitions` structured columns
  before adding an `engine` column; if added, create a migration following the existing
  `app/migrations/*` pattern (SQLite `ALTER TABLE ... ADD COLUMN ... DEFAULT ...`).
- Existing history rows load unchanged (defaults fill new fields).
- Explicitly set `engine="ytdlp"` for existing queued items on load to preserve behavior
  (or allow `engine=None`/`"auto"` and resolve at download time — recommended: resolve
  on load in `DataStore.load` so restarts re-resolve cleanly).
- Keep `YTDLPOpts` and all yt-dlp validation untouched for non-gallery items.

---

## 14. Testing strategy

Backend (pytest, `app/tests`, feature `tests/` dirs):

1. **Detection** — synthetic URLs matching gallery-dl-only and yt-dlp-only extractors;
   verify `auto` resolution and explicit overrides.
2. **Options** — `GalleryDLOpts` precedence and mapping to `config.set`; ensure paths,
   cookies, archive, filters, and passthrough `-o` parse correctly; invalid options raise.
3. **Extractor/enumeration** — `extract()` on direct-image and collection URLs using a
   local HTTP fixture / recorded JSON; assert messages → entries and archive ids.
   Avoid live network in CI (mark as `network`/slow and skip by default).
4. **Runner** — drive `GalleryDLRunner` against a local static file server that mimics a
   gallery; assert hook events produce correct status-queue updates and files land in
   the expected paths. Validate cancellation cleans `.part` files.
5. **StatusTracker multi-file** — feed `file`/`final_name` events; assert `info.files`,
   `is_gallery`, `filename`, `file_size`, and `finished` status.
6. **item_adder routing** — gallery URL → `gallery_processor`; yt-dlp URL unchanged.
7. **Queue/archive** — duplicate detection via native + synthetic archive ids.
8. **Task handler** — `can_handle`/`extract`/`inspect` with a fake definition; assert
   dispatch and archive filtering (mirror `test_generic_task_handler.py`).
9. **Clear/remove** — gallery folder files removed only under the documented guard.

Frontend (vitest, `ui/tests`): engine selector behavior, gallery-dl option form,
gallery rendering component, i18n coverage.

No mocks where a real, local code path is feasible: use a local HTTP fixture server and
real `gallery_dl` extraction against it. Only stub network for third-party sites.

---

## 15. Documentation

- `docs/features.md`: new "Gallery-dl Engine" section (supported sites, engine selection,
  gallery vs. video, archive, cookies, templates).
- `FAQ.md`: gallery-dl env vars, how to force engine, how to install/upgrade.
- `API.md`: the new endpoints + new item fields.
- `README.md`: mention image/gallery support and the dependency.
- `docs/task-definitions.md`: gallery-dl task handler usage (if applicable).
- `plan.md` (this file) stays as the implementation reference.

---

## 16. Phased delivery / milestones

**Phase 0 — foundations (no user-visible change)**
- Add `engine` to `Item`/`ItemDTO`/presets/tasks (default `auto`).
- Add `gallery-dl` dependency + config keys + diagnostics.
- Add `detect()` and `GalleryDLOpts` with unit tests.

**Phase 1 — single-item gallery-dl downloads**
- `GalleryDLRunner` + `GalleryHooks`, `core._download` branch, `item_adder` routing.
- Single image/post/video URL → one history item with `files` list.
- Status/progress/cancel/history parity with yt-dlp.

**Phase 2 — galleries/collections**
- `gallery_processor` expansion into per-post child items (playlist-like).
- `max_items`/range cap; archive id synthesis; duplicate skip.

**Phase 3 — UI + API**
- Engine selector, gallery options editor, gallery grid view, presets/tasks UI.
- Router endpoints + API docs.

**Phase 4 — tasks, installer, polish**
- Scheduled gallery sources; installer/update checks; docs; i18n.
- CLI passthrough escape hatch.

---

## 17. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Option dialect mismatch (yt-dlp `%(x)s` vs gallery-dl `{x}`) | Separate `GalleryDLOpts`; engine-aware UI; validation per engine |
| Multi-file items break single-file assumptions (thumbnails, clear, player) | First-class `files` list + `is_gallery`; guard all single-file code paths; phased rollout |
| `gallery_dl.config` is a process-global singleton | The runner executes in a per-download subprocess; reset/apply config at start; never touch config in the server process |
| Cancellation leaves `.part` files | Hook-driven abort + reuse `TempManager`; verify in tests |
| Archive id collisions between engines | Namespaced synthetic ids (`gallerydl ...`) + separate native archive |
| Live-stream code paths run for gallery items | Force `is_live=False` for gallery-dl items; skip live branches |
| Extractor process-pool pickling of gallery-dl objects | Keep only picklable config dicts across the pool; run extraction in the subprocess, not the pool, when objects aren't picklable |
| CI network flakiness for real sites | Local HTTP fixtures; mark live tests and skip by default |
| Upstream `gallery-dl` API changes | Pin a range; wrap the library surface in `runner.py`/`extractor.py` so only those files change |
| Scheduler handler auto-discovery side effects | Explicit `can_handle` engine gating; unit tests for handler matching |

---

## 18. Open questions

1. Should a gallery be **one history item with N files** or **N items** by default?
   Recommended: one item per URL by default, with opt-in expansion (`gallery_mode`).
2. Should gallery items participate in the existing `download_archive` (yt-dlp format)
   for the "already downloaded" badge, or only use the synthetic id + native archive?
3. Do we want `--zip`/`--cbz` packaged output as the "primary file" for manga archives?
4. Should gallery-dl extraction run through the existing `ExtractorPool` (shares
   concurrency/timeouts) or a dedicated pool (gallery extraction can be long)?
5. Video URLs that both engines support: default preference and whether to fall back
   across engines on failure (e.g., try gallery-dl, then yt-dlp).
6. `gallery-dl[video]` vs plain `gallery-dl` as the shipped dependency (affects image
   size and duplicate `yt-dlp` resolution).

---

## 19. File-by-file change checklist

Backend:
- [ ] `app/features/downloads/items.py` — `Item.engine`, `ItemDTO.engine/is_gallery/files/gallery_count`
- [ ] `app/features/downloads/runtime/core.py` — split `_download` → `_download_ytdlp`/`_download_gallerydl`
- [ ] `app/features/downloads/runtime/item_adder.py` — engine resolution + gallery branch
- [ ] `app/features/downloads/runtime/gallery_processor.py` — new
- [ ] `app/features/downloads/runtime/status_tracker.py` — multi-file finalization
- [ ] `app/features/downloads/runtime/hooks.py` / `utils.py` — gallery progress fields
- [ ] `app/features/downloads/runtime/pool_manager.py` — engine-aware extractor label
- [ ] `app/features/downloads/runtime/queue_manager.py` — gallery folder removal
- [ ] `app/features/gallerydl/{__init__,runner,extractor,opts,utils,router}.py` — new
- [ ] `app/features/gallerydl/tests/*` — new
- [ ] `app/routes/api/gallery_dl.py` — new shim
- [ ] `app/features/tasks/definitions/handlers/gallerydl.py` — new handler
- [ ] `app/features/tasks/schemas.py`, `defs/schemas.py`, `defs/results.py` — engine field
- [ ] `app/features/presets/{schemas,defaults,router,service}.py` — engine + gallery presets
- [ ] `app/library/config.py` — `YTP_GALLERYDL_*`
- [ ] `app/library/PackageInstaller.py`, `UpdateChecker.py`, `diagnostics.py` — install/version
- [ ] `app/main.py` — registration (if needed)
- [ ] `pyproject.toml`, `uv.lock`, `Dockerfile`, `compose.yaml` — dependency

Frontend/docs:
- [ ] `ui/app/components/NewDownload.vue`, `YTDLPOptions.vue`/`GalleryDLOptions.vue`,
      `PresetForm.vue`, `TaskForm.vue`, `history.vue`, `simple.vue`, new `GalleryView.vue`
- [ ] `ui/app/types/*.d.ts`, `ui/i18n/locales/*.json`, `useYtpConfig.ts`
- [ ] `API.md`, `docs/features.md`, `FAQ.md`, `README.md`, `docs/task-definitions.md`
