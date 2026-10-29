# AGENTS.md

Orientation for AI agents and new contributors working in this repository. Read this first, then the
topic-specific docs it points to. Do not re-derive the architecture from scratch.

## What this project is

YTPTube is a self-hosted download manager, automation layer, and web UI for `yt-dlp`, written in
Python ≥3.13 with an aiohttp backend and a Nuxt 4 SPA.

This repository is a **fork** (`origin`: `jthickma/ytptube-gallery-dl`, `upstream`: `arabcoders/ytptube`)
that adds **gallery-dl as a second download engine** alongside yt-dlp. Everything upstream still applies;
the fork-specific delta is:

- `app/features/gallerydl/` — a complete gallery-dl integration (engine detection, option dialect,
  in-process runner, extractor pool adapter, API routes).
- `engine` (`auto` | `ytdlp` | `gallerydl`) and `gallerydl` (CLI/JSON options string) fields on downloads,
  presets and task definitions.
- Gallery history shape: `is_gallery`, `gallery_count`, `gallery_metadata`, `files[]` per item.
- UI: `GalleryView.vue`, `GalleryDLOptions.vue`, `DownloadEngineFields.vue`,
  `ui/app/utils/download-engine.ts`.
- Design rationale: `plan.md`. User-facing behavior: `docs/gallery-dl.md`.

Upstream branch flow: work targets **`dev`**, never `master`. Upstream policy (`CONTRIBUTING.md`) requires
maintainer approval before opening a PR; unsolicited PRs are closed. Do not commit unless asked.

## Repository layout

| Path | Contents |
| --- | --- |
| `app/main.py` | ASGI entrypoint, `Main` class, service attach order, `--dev` reload via watchfiles |
| `app/local.py`, `cli.py`, `app/upgrader.py` | native/PyInstaller entry, CLI entry, pre-start package upgrades |
| `app/library/` | cross-cutting infra: DI, routing, HTTP/WS servers, config, DB, events, logging, utils |
| `app/features/` | feature packages (`auth`, `cli`, `conditions`, `core`, `dl_fields`, `downloads`, `gallerydl`, `media`, `notifications`, `presets`, `streaming`, `tasks`, `ytdlp`) |
| `app/routes/api/`, `app/routes/socket/` | thin shims that import feature routers so `HttpAPI` can discover routes |
| `app/migrations/` | timestamped SQL migration modules (`upgrade`/`downgrade`) |
| `app/schema/` | exported JSON schemas mirroring pydantic schemas |
| `app/tests/`, `app/features/*/tests/` | pytest suites (feature tests are colocated) |
| `ui/` | Nuxt 4 + Vue 3 + `@nuxt/ui` v4 + Tailwind 4 SPA, Bun-managed |
| `webext/` | plain-JS browser extension for sending links |
| `container/`, `Dockerfile`, `compose.yaml` | container build/runtime scripts and dev stack |
| `yt-dlp` | container-only bash wrapper that runs `python -m yt_dlp` with the persisted user-site on `PATH`/`PYTHONPATH` |
| `docs/`, `API.md`, `FAQ.md`, `plan.md` | prose documentation; `API.md` is the full API reference |

Existing docs to consult instead of duplicating:

- `docs/features.md` — behavior of downloads, tasks, presets, conditions, notifications.
- `docs/gallery-dl.md` — gallery-dl behavior, env vars, API examples.
- `docs/authentication.md`, `docs/media-handlers.md`, `docs/task-definitions.md`, `docs/native-builds.md`.
- `API.md` — endpoint reference; `plan.md` — gallery-dl design doc.

## Backend architecture

### Startup sequence (`app/main.py`)

`Main.start()` wires services by attaching them to the aiohttp app. Order matters:

1. `SqliteStore`, `DownloadsRepository`, `AuthService`, `BackgroundWorker`, `Scheduler`, `PlayerManager`,
   `Cache`, `TerminalSessionManager`
2. `HttpSocket` then `HttpAPI` (servers/routes)
3. `PresetsRepository`, `Tasks`, `Notifications`, `Conditions`, `DLFields`, task definitions repository,
   `ExtractorPool`, `DownloadQueue`, `UpdateChecker`, `ResourceTracker`
4. `close_shared_clients` on shutdown

Lifecycle events are emitted through `EventBus` (`app/library/Events.py`): `STARTUP` → `LOADED` →
`STARTED` → `SHUTDOWN`. Services subscribe to `Events.STARTED` for deferred initialization (download queue,
tasks scheduler, etc.).

### Dependency injection (`app/library/Services.py`)

A name/type-keyed singleton registry. Handlers declare parameters and the framework resolves them:

```python
async def handler(request, queue, repo: DownloadsRepository) -> web.Response: ...
# HttpAPI/HttpSocket call Services.get_instance().handle_async(handler, request=request, ...)
```

`ServiceEntry` supports `Annotated[T, ...]` and `T | None` unwrapping. Register new shared objects with
`Services.get_instance().add("name", instance)` inside the owning service's `attach()`.

### Singletons

`app/library/Singleton.py` provides `Singleton` and `ThreadSafe` metaclasses plus `_reset_singleton` for
tests. Most services use `get_instance()`; `PlayerManager` is constructed directly.

### Routing (`app/library/router.py`, `app/library/HttpAPI.py`)

- `@route(method, path, name=None, public=False, same_origin=False, cookie_only=False, optional_auth=False, auth_only=False, no_slash=False)`
  appends to a module-level `ROUTES` dict. `no_slash` auto-registers a variant without the trailing slash.
- `HttpAPI` imports every module in `app/routes/api/` (`load_modules`), applies `auth_middleware`, CORS,
  `OPTIONS`, base-path rewriting of served HTML, and redacts `apikey`/`ticket` in access logs.
- Route modules in `app/routes/api/` are usually one-line re-exports, e.g.
  `app/routes/api/gallery_dl.py` → `from app.features.gallerydl.router import *`. Put real handlers in the
  feature package, not in `app/routes/`.

### WebSocket (`app/library/HttpSocket.py`)

`WebSocketHub` serves `/ws`. Socket routes live in `app/routes/socket/` (`connection.py`, `history.py`) with
`RouteType.SOCKET`. `Events.frontend()` payloads are broadcast to clients. Clients authenticate with a
short-lived ticket (`ytp_ws_...`, 30s TTL) minted by `AuthService`, not the session cookie.

### Database (`app/library/sqlite_store.py`, `app/features/downloads/models.py`)

- SQLite via SQLAlchemy async + aiosqlite, WAL mode, `busy_timeout=5000`, `foreign_keys=ON`.
- Migrations run on connect; forked Caribou (`app/library/migrate.py`). Add new ones with
  `app/scripts/create_migration.py` (timestamp-prefixed filename, `upgrade`/`downgrade` functions).
- Session dependency: `app/features/core/deps.py::get_session`.
- Single `history` table, discriminated by `type` (`queue`/`done`), with PK `id`, `url` (unique) and a JSON
  `data` blob. Indexes include `type`, `url`, json `$.status`, and `(type, $.extras.source_id)`.
- Reads/writes go through `DownloadsRepository`, which batches operations on an async queue
  (`max_pending=200`, `flush_interval=0.05`) and filters with `json_extract` via
  `app/library/operations.py::Operation`.

## Download pipeline

```
Item (request DTO)  ──add()──▶  resolve_engine()  ──▶  ItemDTO (+ DataStore)  ──▶  PoolManager
                                                                                    │
                                              subprocess: Download._download() ─────┘
                                                   ├─ engine == "gallerydl" → GalleryDLRunner
                                                   └─ otherwise            → yt-dlp + hooks
                                                                                    │
                                           status_queue / EventBus.ITEM_UPDATED → queue ⇒ history
```

Key files in `app/features/downloads/`:

- `items.py` — `Item` (request: `url`, `engine`, `gallerydl`, `preset`, `folder`, `cookies`, `template`,
  `cli`, `extras`, `requeued`, `auto_start`, `force_start`) and `ItemDTO` (runtime/history record with
  `_id`, progress fields, archive fields, `files`, `gallery_metadata`, `is_gallery`, `gallery_count`).
  `Item.format()` validates engine values, preset existence, and parses `cli` in the correct dialect.
- `store.py` — `DataStore` in-memory `OrderedDict` over the repository; `StoreType.QUEUE` = `"queue"`,
  `StoreType.HISTORY` = `"done"`.
- `repository.py` — `DownloadsRepository` batching persistence layer.
- `runtime/item_adder.py` — `add()` resolves the engine, applies preset values, and dispatches to
  `add_gallery()` (`runtime/gallery_processor.py`) or the yt-dlp path.
- `runtime/queue_manager.py` — `DownloadQueue` singleton owning both stores plus `PoolManager`; exposes
  `add/start/retry/force_start/position/pause/cancel/clear`; registers cron jobs via `Scheduler`:
  `check_for_stale`, `check_live`, `check_retries` (if `retry > 0`), `cleanup_thumbnails`, and
  `delete_old_history` (if `auto_clear_history_days > 0`).
- `runtime/pool_manager.py` — `PoolManager`: global `max_workers` semaphore plus per-extractor limits
  (`runtime/utils.py::get_extractor_limit`, `max_workers_per_extractor`), `force_start`/live bypass,
  adaptive backoff, moves finished items queue→history.
- `runtime/core.py` — `Download` orchestrates one job. `start()` creates the status queue, temp path,
  `StatusTracker`, `HookHandlers`, then spawns the process via `ProcessManager`; `_download()` dispatches to
  `_download_gallerydl()` or `_download_ytdlp()`.
- `runtime/bootstrap.py` — `ensure_download_runtime()` re-initializes DB + presets inside spawned workers
  (spawn start method). Any new global state needed in the child process must be bootstrapped here.
- `runtime/{status_tracker,temp_manager,process_manager,hooks,video_processor,playlist_processor,monitors}.py`.

## yt-dlp layer (`app/features/ytdlp/`)

`extractor.py` (`ExtractorPool`, `extract_info_sync`), `ytdlp.py` (`YTDLP` subclass), `ytdlp_opts.py`
(`YTDLPOpts`/`ARGSMerger`), `archiver.py`, `mini_filter.py`, `outtmpl.py`, `filename.py`, `patches.py`,
`shortcut.py`, `utils.py` (`arg_converter`, `get_archive_id`, archive helpers), plus bundled plugins in
`yt_dlp_plugins/` (`extractor/generic_browser.py`, `postprocessor/nfo_maker.py`).

Option precedence (low → high): default preset → named preset → CLI string → per-request user options.

## gallery-dl layer (`app/features/gallerydl/`)

- `detect.py` — `ENGINES = ("auto", "ytdlp", "gallerydl")`, `IMAGE_SITES`, `gallerydl_matches()`
  (lru-cached `gallery_dl.extractor.find`), and `resolve_engine()`. Precedence:
  explicit item engine → preset `engine` → auto detection. Auto returns `ytdlp` when gallery-dl is disabled
  or `gallerydl_auto` is off; skips `gallerydl_exclude_sites`; prefers gallery-dl for
  `gallerydl_sites`/`IMAGE_SITES`/`extras["engine_preference"] == "gallerydl"`; otherwise falls back to
  gallery-dl only when yt-dlp has no real extractor (generic/html5mediaembed).
- `opts.py` — the gallery-dl option dialect. `gallerydl_arg_converter()` accepts either a JSON object or a
  CLI flag string (parsed with gallery-dl's own parser; `-h/--version`, URL and job-mode flags are rejected).
  `GalleryDLOpts` merges defaults < preset < CLI < per-item. `build_options()` sets the native sqlite
  archive (`gallerydl-archive.sqlite3`, `archive-event=after`), cache file, `output.mode=null`,
  `base-directory` under the app download path, `_max_items`, optional `_config_files`.
  `apply_options()` must only be called **inside** an isolated worker — it mutates `gallery_dl.config`.
- `runner.py` — `GalleryDLRunner` drives gallery-dl in-process with job hooks, emits status/progress on the
  status queue, honors cancellation (`SystemExit(130)` plus cancel event), cleans `.part` files, and records
  ZIP/CBZ outputs.
- `extractor.py` — `extract()`/`extract_sync()` bound to `ExtractorPool` for metadata-only lookups.
- `utils.py` — `gallerydl_archive_id()` (sha256 of the URL, `"gallerydl <category>:<hash24>"`),
  `history_archive()` (`<config_path>/gallerydl-history.txt`), `file_record()`, `remove_files()`.
  All path handling is sandboxed with `is_relative_to`.
- `router.py` — `POST /api/gallery-dl/detect/`, `GET|POST /api/gallery-dl/options/`,
  `GET /api/gallery-dl/extractors/`, `POST /api/gallery-dl/convert/`, `GET|POST /api/gallery-dl/url/info/`,
  `GET /api/gallery-dl/version/`.

Two archives exist and are distinct:

- **Native gallery-dl sqlite archive** — file-level dedupe across recurring task runs.
- **App source-level history archive** (`gallerydl-history.txt`) — powers `is_archived`/archive endpoints.
  Deleting history does not clear the native archive.

## Tasks, presets, conditions, notifications

- Tasks (`app/features/tasks/`): `Tasks` singleton schedules one cron per task (`task-cronjob-{id}`) and
  dispatches `Item` with `extras.source_handler="Tasks"`, `source_id`, and `ignore_conditions`. Handlers are
  discovered from `definitions/handlers/` (`_base_handler.py` plus `generic`, `rss`, `gallerydl`, `tver`,
  `twitch`, `youtube`). A dispatcher cron (`tasks_handler_timer`) fans out with random jitter. Tasks store
  the same `engine`/`gallerydl` options as one-off downloads and require an archive to be configured.
- Presets/conditions/dl_fields/notifications: pydantic schemas in each feature's `schemas.py`, mirrored to
  `app/schema/*.json`. `Preset` gained `engine`/`gallerydl` in migration
  `20261001120000_add_download_engines.py`. Changing a schema usually requires updating the JSON copy.

## Auth, media, streaming

- `app/features/auth/` — bcrypt hashing, `ytp_session` cookies, `ytp_`-prefixed API keys, WS tickets, OIDC
  and trusted remote-user via `config.toml` `[auth]`, login rate limit (5/60s), proxy-aware IP resolution in
  `middleware.py`. `YTP_DISABLE_AUTH` disables the whole layer.
- `app/features/media/` — `Handler` subclasses discovered from `handlers/` (e.g. `widevine.py`), selected by
  yt-dlp `media` options.
- `app/features/streaming/` — `PlayerManager` (IDLE_TTL 300s, PLAYER_TTL 900s, MAX_RESOURCES 32),
  `encoding.py`, `library/{ffprobe,subtitle,thumbnail}.py`.

## Configuration (`app/library/config.py`)

- `Config` singleton; every attribute maps to `YTP_<UPPER_NAME>` (e.g. `max_workers` → `YTP_MAX_WORKERS`).
  Special-cased paths: `YTP_CONFIG_PATH`, `YTP_TEMP_PATH`, `YTP_DOWNLOAD_PATH`. `.env` is loaded from the
  config path. `config.toml` holds non-env settings such as external auth.
- Typed attribute lists (`_boolean_vars`, `_int_vars`, `_float_vars`, `_immutable`, `_manual_vars`,
  `_frontend_vars`) decide coercion and what is exposed to the UI. Add new vars to the right lists.
- gallery-dl vars: `YTP_GALLERYDL_ENABLED`, `YTP_GALLERYDL_AUTO`, `YTP_GALLERYDL_SITES`,
  `YTP_GALLERYDL_EXCLUDE_SITES`, `YTP_GALLERYDL_FILENAME`, `YTP_GALLERYDL_ARCHIVE`,
  `YTP_GALLERYDL_CONFIG`, `YTP_GALLERYDL_MAX_ITEMS`, `YTP_GALLERYDL_TMP_USE`.
- Defaults live under `var/config`, `var/tmp`, `var/downloads` (tracked only via `.gitkeep`; everything else
  is gitignored).

## Static/SPA serving

`app/routes/api/_static.py` resolves the built SPA from `YTP_STATIC_UI_PATH`, `app/ui/exported`, then
`../ui/exported`, with SPA fallback routing. Production builds use base path `/_base_path/`; middleware
rewrites served HTML accordingly. `simple_mode` cookie switches to the simplified UI.

## Frontend (`ui/`)

- Nuxt 4, `ssr: false`, Vue 3, `@nuxt/ui` v4, Tailwind 4, `@nuxtjs/i18n` (en, ar, fr, zh, ja). Bun is the
  package manager. Dev server on port 8082 with `baseURL: "/"`; production build uses `/_base_path/`.
  Output: `bun run generate` → `ui/exported` (prod) / `ui/dist` (dev), both gitignored.
- In dev, `NUXT_API_URL` enables a nitro `devProxy` for `/api/` to the backend; without it the SPA calls its
  own origin. Env vars used by the UI: `NUXT_API_URL`, `NUXT_PUBLIC_WSS`.
- Pages in `ui/app/pages/` (`index`, `history`, `simple`, `tasks`, `task_definitions`, `presets`,
  `conditions`, `dl_fields`, `notifications`, `diagnostics`, `logs`, `status`, `limits`, `console`,
  `browser`, `setup`, `login`, `changelog`, `docs`).
- State via composables in `ui/app/composables/` (`useQueueState`, `useHistoryState`, `useAppSocket`
  for WS reconnect + queue backfill, `useMode`, `useAuth`, `usePresetEditor`, …).
- HTTP via `ui/app/utils/index.ts` (`request`, `ensure_api_success`, `uri`). Types in `ui/app/types/*.d.ts`
  (e.g. `item.d.ts` declares `DownloadEngine` and `GalleryFile`).
- Engine UI: `utils/download-engine.ts` (`detectDownloadEngine`, `convertGalleryOptions`),
  `GalleryDLOptions.vue`, `DownloadEngineFields.vue`; gallery rendering uses `GalleryView.vue` in
  `pages/history.vue` and `pages/simple.vue` when `engine === 'gallerydl'`.
- Any user-visible string must be added to all five locales under `ui/i18n/`; `bun run i18n:check` enforces it.

## Tests, checks, CI

Backend (repo root):

```bash
uv run ruff format --check app/
uv run ruff check app/
uv run ty check app/
uv run pytest app/ -q
```

pytest config: `testpaths = app/tests, app/features`, `-q --tb=short`, 30s per-test timeout, 300s session timeout,
pytest-asyncio with explicitly marked async tests/fixtures (no global `asyncio_mode`).
`app/conftest.py` provides the `test_client` fixture built on `app/tests/helpers.py::make_test_app` (isolated
in-memory SQLite, per-run temp roots via `set_test_env`). Use `test_client` for route tests; never touch the
real `var/` tree.

Frontend (from `ui/`):

```bash
bun run format:check   # oxfmt
bun run lint:ci        # eslint
bun run typecheck      # nuxt typecheck
bun run lint:tsc       # vue-tsc
bun run test:ci        # bun test
bun run i18n:check
```

Pre-commit: `./.githooks/install` (or `--force`). The hook detects Python vs frontend changes, runs checks in
parallel background jobs, and also runs any scripts in `.git/hooks/pre-commit.d/{,backend,frontend}`.

CI: `.github/workflows/main.yml` builds the SPA, regenerates `CHANGELOG.json`, and publishes multi-arch
Docker images (DockerHub slug `ytptube-gallery-dl`, GHCR); `build-pr.yml` validates PRs; `native-build.yml`
cuts PyInstaller builds from `app.spec` (collects `gallery_dl` submodules and
`app.features.media.handlers` — update it if you add runtime-imported packages).

A `diagnose-ci-failures` skill exists in `.agents/skills/` (mirrored into `.claude`, `.continue`, `.goose`).

## Local development

```bash
uv run python -m app.main --dev              # backend, auto-reload via watchfiles
cd ui && NUXT_API_URL=http://127.0.0.1:8081 bun run dev   # frontend :8082, proxies /api/
docker compose up                            # full stack incl. chromium, chrome-cdp-proxy, flaresolverr
```

With a built UI present (`ui/exported`), the backend serves the SPA itself, so the dev server is only needed
for frontend work.

## Conventions and gotchas

- Python: 4-space indent, double quotes, 120-column lines (ruff). Non-Python files: 2-space indent
  (`.editorconfig`). Keep markers/`extra={...}` structured logging style used throughout.
- Import modules lazily inside functions when the module pulls in `gallery_dl`/`yt_dlp` or creates cycles —
  existing code does this consistently (e.g. `Config`, `Presets` imports inside functions).
- Anything executed in the download subprocess must call `ensure_download_runtime()` first (or use the
  helpers that do) because workers are spawned, not forked.
- `apply_options()` for gallery-dl is process-global; never call it on the event loop or in a shared request
  handler.
- Template dialects differ: gallery-dl uses `{field}.{extension}`; yt-dlp uses `%(field)s`. `build_options()`
  raises a `ValueError` on `%(` in a gallery template — keep that guard.
- Automatic engine routing is config-sensitive; when changing `resolve_engine()`, extend the tests in
  `app/features/gallerydl/tests/` and keep `IMAGE_SITES` curated rather than open-ended.
- Never construct filesystem paths from user input without the sandbox checks used in
  `app/library/Utils.py::calc_download_path` and `app/features/gallerydl/utils.py`.
- Deleting gallery files must never delete a shared source folder; use `remove_files()` semantics.
- Config/env changes usually need updates in three places: the `Config` attribute, the typed var lists, and
  `docs/` (plus `api/schema` JSON if it is user-editable).
- Public API additions belong in a feature `router.py` with a shim in `app/routes/api/`; document them in
  `API.md` and note gallery-related ones in `docs/gallery-dl.md`.
