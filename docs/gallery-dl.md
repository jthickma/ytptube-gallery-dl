# Gallery-dl downloads

This fork supports gallery-dl alongside yt-dlp for images, collections, and supported videos.
The dependency is installed by `uv sync` and included in source-built Docker images.
Use an image built from this fork; the upstream YTPTube image does not contain these changes.

## Download a gallery

1. Open the download form and paste a source URL, such as `https://vsco.co/USERNAME/gallery`.
2. Leave **Download engine** on **Auto**, or select **gallery-dl** explicitly.
3. Choose `gallery_full` to write metadata, `gallery_images` to exclude videos where supported,
   or `gallery_video` to enable videos where supported.
4. Click **Add download**. Open the finished item's **View gallery** action in History
   to browse its files, play videos/audio, or download individual files.

One source URL produces one queue/history item with multiple files. Native gallery-dl source
folders and filenames are preserved beneath the selected download folder. Leave the filename
field empty for native behavior; custom templates use `{filename}.{extension}` syntax,
not yt-dlp's `%(...)s` syntax. Options accept gallery-dl CLI flags or a JSON configuration object:

```text
--write-metadata --range 1-50 -o videos=false
```

```json
{"extractor": {"vsco": {"videos": false}}, "retries": 5}
```

Only download options are accepted. Help, version, URL-listing, simulation, and other job modes
are rejected. JSON config files are supported with `--config`; YAML/TOML config files and
standalone CLI passthrough are not supported. The console command action remains a yt-dlp
feature; run gallery-dl through the queue. **Show compiled options** displays gallery-dl config.

Options merge in order: app defaults, preset, item. The app always sets the base download folder.
Keep yt-dlp flags in yt-dlp presets and gallery-dl flags in the separate gallery-dl options field.
Gallery-dl presets may also use the regular CLI field. Uploaded Netscape cookies are passed
through the same cookie field used for video downloads.

## Automatic selection and recurring sources

Auto selects gallery-dl for image-oriented sources and URLs only gallery-dl supports.
Video sources supported by both engines generally keep yt-dlp. Explicit item engine selection
wins over the preset, which wins over automatic detection. A scheduled task stores the same
engine and gallery-dl options as a one-off download.

Recurring tasks revisit the source URL on every run. A native SQLite file archive skips previously
downloaded media while allowing new files to be discovered. The app's source-level history archive
is separate from this native archive. Deleting history does not clear the native archive.
Files still present from a previous run remain visible in the source's gallery when its folder
is unchanged. Changing folders does not move old media or reset the archive.

Deleting files removes recorded gallery files and matching sidecars; it does not remove a shared
source folder. Cancellation preserves finished media and removes touched partial files beneath
the download folder. Configured temporary directories can retain partial files after cancellation.

## Configuration

Set these environment variables before starting the app:

| Variable | Default | Purpose |
| --- | --- | --- |
| `YTP_GALLERYDL_ENABLED` | `true` | Enable gallery-dl engine selection. |
| `YTP_GALLERYDL_AUTO` | `true` | Enable automatic routing to gallery-dl. |
| `YTP_GALLERYDL_SITES` | empty | Comma-separated extractor categories preferred by Auto. |
| `YTP_GALLERYDL_EXCLUDE_SITES` | empty | Categories excluded from Auto; explicit selection still works. |
| `YTP_GALLERYDL_FILENAME` | empty | Default gallery filename template; empty keeps native names. |
| `YTP_GALLERYDL_ARCHIVE` | empty | Native archive path; default is `gallerydl-archive.sqlite3` in the config folder. |
| `YTP_GALLERYDL_CONFIG` | empty | Optional JSON config file loaded inside workers. |
| `YTP_GALLERYDL_MAX_ITEMS` | `0` | Per-job file limit; zero means unlimited. |
| `YTP_GALLERYDL_TMP_USE` | `false` | Use the app's temporary directory for gallery partial files. |

Keep the config directory persistent to retain `gallerydl-archive.sqlite3`,
`gallerydl-cache.sqlite3`, and `gallerydl-history.txt`. Config files and arbitrary `-o` options
should be supplied by trusted users, just like yt-dlp options.

## API

Existing history-add requests, preset records, and task records accept `engine`
(`auto`, `ytdlp`, or `gallerydl`) and `gallerydl` (CLI/JSON string).

Example body for `POST /api/history` using the deployment's existing authentication:

```json
[{
  "url": "https://vsco.co/USERNAME/gallery",
  "engine": "gallerydl",
  "gallerydl": "--write-metadata",
  "folder": "images",
  "auto_start": true
}]
```

Gallery history includes `engine`, `is_gallery`, `gallery_count`, `gallery_metadata`, and `files`.
Each file has a filename relative to the item's folder, size, MIME type, and metadata.
Files use the existing authenticated `/api/download/{path}` endpoint.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/gallery-dl/detect/` | Resolve `{url, engine?, preset?, extras?}` to `{engine}`. |
| `GET /api/gallery-dl/options/` | List supported parser flags and help. |
| `POST /api/gallery-dl/options/` | Compile a download request into `{options}`. |
| `POST /api/gallery-dl/convert/` | Convert `{args: "--write-metadata"}` into `{options}`. |
| `GET /api/gallery-dl/extractors/` | List extractor categories and URL patterns. |
| `GET` / `POST /api/gallery-dl/url/info/` | Inspect a download request without downloading. Optional `limit` bounds enumeration; `resolve=true` follows child sources. |
| `GET /api/gallery-dl/version/` | Installed version and available version from update checks. |

API-only `extras.gallery_mode="expand"` queues discovered child source URLs separately;
the default queues the original source and lets gallery-dl traverse it natively.
