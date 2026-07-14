from __future__ import annotations

import contextlib
import io
import shlex
from typing import TYPE_CHECKING, Any

from gallery_dl import option, version

from app.library.Utils import calc_download_path

if TYPE_CHECKING:
    from pathlib import Path

DOWNLOADER = "gallery-dl"
VERSION = version.__version__

# YTPTube owns the target directory and the machine-readable manifest. Output-only
# and process-management modes do not represent downloadable queue jobs.
RESERVED_OPTIONS = {
    "-d",
    "--destination",
    "-D",
    "--directory",
    "-i",
    "--input-file",
    "-I",
    "--input-file-comment",
    "-x",
    "--input-file-delete",
    "-g",
    "--get-urls",
    "-G",
    "--resolve-urls",
    "-j",
    "--dump-json",
    "-J",
    "--resolve-json",
    "-s",
    "--simulate",
    "-E",
    "--extractor-info",
    "-K",
    "--list-keywords",
    "-N",
    "--print",
    "--Print",
    "--print-to-file",
    "--Print-to-file",
    "--list-modules",
    "--list-extractors",
    "--no-download",
    "--no-input",
    "--no-colors",
    "-c",
    "--config",
    "--config-json",
    "--config-yaml",
    "--config-toml",
    "--config-type",
    "--config-ignore",
    "--config-create",
    "--config-status",
    "--config-open",
    "-S",
    "--server",
    "-U",
    "--update",
    "--update-to",
    "--update-check",
    "-h",
    "--help",
    "--version",
}


def _option_name(token: str) -> str:
    return token.split("=", 1)[0]


def parse_cli(cli: str) -> list[str]:
    try:
        args = shlex.split(cli or "", posix=True)
    except ValueError as exc:
        msg = f"Failed to parse command options for gallery-dl. {exc!s}"
        raise ValueError(msg) from exc

    parser = option.build_parser()
    blocked = {_option_name(token) for token in args if _option_name(token) in RESERVED_OPTIONS}
    short_actions = {
        flag: action
        for action in parser._actions
        for flag in action.option_strings
        if flag.startswith("-") and not flag.startswith("--") and len(flag) == 2
    }
    for token in args:
        if not token.startswith("-") or token.startswith("--") or len(token) <= 2:
            continue
        for character in token[1:]:
            flag = f"-{character}"
            action = short_actions.get(flag)
            if action is None:
                break
            if flag in RESERVED_OPTIONS:
                blocked.add(flag)
            if action.nargs != 0:
                break
    if blocked:
        joined = ", ".join(sorted(blocked))
        msg = f"gallery-dl option(s) managed by YTPTube cannot be used here: {joined}."
        raise ValueError(msg)

    dummy_url = "https://example.com/gallery"
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            parsed = parser.parse_args([*args, dummy_url])
    except SystemExit as exc:
        detail = stderr.getvalue().strip().splitlines()
        message = detail[-1] if detail else f"parser exited with status {exc.code}"
        message = message.replace("gallery-dl: error: ", "")
        msg = f"Failed to parse command options for gallery-dl. {message}"
        raise ValueError(msg) from exc

    if parsed.urls != [dummy_url]:
        msg = "gallery-dl command options must not contain additional URLs."
        raise ValueError(msg)

    defaults = option.build_parser().parse_args([dummy_url])
    indirect_blocked: set[str] = set()
    for action in parser._actions:
        reserved = [flag for flag in action.option_strings if flag in RESERVED_OPTIONS]
        if reserved and getattr(parsed, action.dest, None) != getattr(defaults, action.dest, None):
            indirect_blocked.update(reserved)
    if indirect_blocked:
        joined = ", ".join(sorted(indirect_blocked))
        msg = f"gallery-dl option(s) managed by YTPTube cannot be used here: {joined}."
        raise ValueError(msg)

    return args


def build_args(
    *,
    url: str,
    cli: str,
    download_dir: str,
    template: str | None = None,
    cookie_file: Path | None = None,
    manifest_file: Path | None = None,
) -> list[str]:
    url = url.strip()
    if not url:
        msg = "url param is required."
        raise ValueError(msg)

    args = parse_cli(cli)
    command = [*args, "--config-ignore", "--no-input", "--no-colors", "--destination", download_dir]

    if template:
        command.extend(("--filename", template))
    if cookie_file:
        command.extend(("--cookies", str(cookie_file)))
    if manifest_file:
        command.extend(("--Print-to-file", "after:{_path}", str(manifest_file)))
        command.extend(("--Print-to-file", "skip:{_path}", str(manifest_file)))

    command.append(url)
    return command


def build_shell_command(data: dict[str, Any], download_path: str) -> tuple[str, dict[str, Any]]:
    cli = str(data.get("cli") or "")
    target = calc_download_path(download_path, str(data.get("folder") or ""), create_path=False)
    args = build_args(
        url=str(data.get("url") or ""),
        cli=cli,
        download_dir=target,
        template=str(data.get("template") or "") or None,
    )
    command = shlex.join(["gallery-dl", *args])
    return command, {"command": command, "gallery_dl": {"version": VERSION, "args": args}}


def get_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    parser = option.build_parser()
    for group in parser._action_groups:
        group_name = str(group.title or "Options").removesuffix(" Options")
        for action in group._group_actions:
            flags = [flag for flag in action.option_strings if flag]
            if not flags or action.help is None or action.help == option.argparse.SUPPRESS:
                continue
            options.append(
                {
                    "flags": flags,
                    "description": str(action.help),
                    "group": group_name,
                    "ignored": any(flag in RESERVED_OPTIONS for flag in flags),
                }
            )
    return options
