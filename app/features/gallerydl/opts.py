import copy
import json
import shlex
from pathlib import Path

from app.library.Utils import calc_download_path


def _invalid(message, *_):
    raise ValueError(str(message))


def parse_cli(args: str):
    """Use upstream's parser without allowing argparse to exit the API process."""
    from gallery_dl import job, option

    parser = option.build_parser()
    parser.error = _invalid
    parser.exit = _invalid
    tokens = shlex.split(args)
    if any(token in {"-h", "--help", "--version"} for token in tokens):
        msg = "Help and version flags are not download options."
        raise ValueError(msg)
    parsed = parser.parse_args(tokens)
    if (
        parsed.urls
        or parsed.input_files
        or parsed.list_modules
        or parsed.dump_json is not None
        or parsed.list_urls is not None
        or parsed.jobtype not in (None, job.DownloadJob)
    ):
        msg = "Options must configure a download; put source URLs in the URL field."
        raise ValueError(msg)
    # Config files are deliberately loaded in worker processes only.
    return parsed


def gallerydl_arg_converter(args: str) -> dict:
    if not args or not args.strip():
        return {}
    if args.lstrip().startswith("{"):
        data = json.loads(args)
        if not isinstance(data, dict):
            msg = "Gallery-dl configuration must be a JSON object."
            raise ValueError(msg)
        return data
    parsed = parse_cli(args)
    result = {}
    for path, key, value in parsed.options:
        target = result
        for part in path:
            target = target.setdefault(part, {})
        target[key] = value
    if parsed.filename:
        result["filename"] = "{filename}.{extension}" if parsed.filename == "/O" else parsed.filename
    if parsed.directory is not None:
        result.update({"base-directory": parsed.directory, "directory": []})
    if parsed.postprocessors:
        result["postprocessors"] = parsed.postprocessors
    if parsed.options_pp:
        result["postprocessor-options"] = parsed.options_pp
    if parsed.abort:
        result["skip"] = "abort:" + parsed.abort
    if parsed.terminate:
        result["skip"] = "terminate:" + parsed.terminate
    if parsed.cookies_from_browser:
        browser, _, profile = parsed.cookies_from_browser.partition(":")
        browser, _, keyring = browser.partition("+")
        browser, _, domain = browser.partition("/")
        profile, _, container = profile.partition("::")
        result["cookies"] = [browser, profile or None, keyring or None, container or None, domain or None]
    files = (parsed.configs_extra or []) + (parsed.configs_json or [])
    if parsed.configs_yaml or parsed.configs_toml:
        msg = "Use a JSON gallery-dl config file or JSON options for this engine."
        raise ValueError(msg)
    if files:
        result["_config_files"] = files
    return result


class GalleryDLOpts:
    """Independent option dialect with defaults < preset < item precedence."""

    def __init__(self):
        self.options: dict = {}

    @classmethod
    def get_instance(cls):
        return cls()

    def add(self, options: dict):
        def merge(target, values):
            for key, value in values.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    merge(target[key], value)
                else:
                    target[key] = copy.deepcopy(value)

        merge(self.options, options)
        return self

    def add_raw(self, args: str):
        return self.add(gallerydl_arg_converter(args))

    def preset(self, name: str):
        from app.features.presets.service import Presets

        if preset := Presets.get_instance().get(name):
            if preset.engine == "gallerydl":
                self.add_raw(preset.cli)
            self.add_raw(preset.gallerydl)
            if preset.engine == "gallerydl" and preset.template:
                self.add({"filename": preset.template})
        return self

    def get_all(self):
        return copy.deepcopy(self.options)


def build_options(item, config=None) -> dict:
    from app.library.config import Config

    config = config or Config.get_instance()
    options = {
        "extractor": {
            "archive": config.gallerydl_archive or str(Path(config.config_path) / "gallerydl-archive.sqlite3"),
            "archive-event": "after",
            "timeout": 30,
        },
        "output": {"mode": "null"},
        "cache": {"file": str(Path(config.config_path) / "gallerydl-cache.sqlite3")},
    }
    if config.gallerydl_filename:
        options["extractor"]["filename"] = config.gallerydl_filename
    if config.gallerydl_config:
        options["_config_files"] = [config.gallerydl_config]
    builder = GalleryDLOpts.get_instance().add(options)
    builder.preset(item.preset)
    if item.engine == "gallerydl":
        builder.add_raw(item.cli or "")
    builder.add_raw(item.gallerydl or "")
    if item.template:
        if "%(" in item.template:
            msg = "Gallery-dl templates use {field} syntax. Set a gallery-dl filename template."
            raise ValueError(msg)
        builder.add({"filename": item.template})
    result = builder.get_all()
    # Root-level values take precedence over site configs in upstream. Contain
    # files under the app's folder, while preserving extractor.directory_fmt.
    result["base-directory"] = calc_download_path(config.download_path, item.folder)
    if config.gallerydl_max_items > 0:
        result["_max_items"] = config.gallerydl_max_items
    return result


def apply_options(options: dict) -> None:
    """Only call inside an isolated extractor/download worker."""
    from gallery_dl import config

    config.clear()
    if files := options.get("_config_files"):
        try:
            config.load(files, strict=True)
        except SystemExit as exc:
            msg = "Failed to load gallery-dl configuration file."
            raise ValueError(msg) from exc
    for key, value in options.items():
        if not key.startswith("_"):
            config.set((), key, copy.deepcopy(value))
