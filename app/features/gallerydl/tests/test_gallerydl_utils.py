from pathlib import Path

import pytest

from app.features.gallerydl.utils import VERSION, build_args, build_shell_command, get_options, parse_cli


def test_parse_cli_accepts_gallery_selection_flags() -> None:
    assert parse_cli('--range "1-5" --filter "extension in (\'jpg\', \'png\')"') == [
        "--range",
        "1-5",
        "--filter",
        "extension in ('jpg', 'png')",
    ]


@pytest.mark.parametrize(
    "flag",
    [
        "--destination /tmp/out",
        "-d/tmp/out",
        "--Print after:{_path}",
        "--no-download",
        "--config custom.json",
    ],
)
def test_parse_cli_rejects_app_managed_modes(flag: str) -> None:
    with pytest.raises(ValueError, match="managed by YTPTube"):
        parse_cli(flag)


def test_parse_cli_rejects_extra_urls() -> None:
    with pytest.raises(ValueError, match="must not contain additional URLs"):
        parse_cli("https://other.example/post")


def test_build_args_forces_managed_output_and_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "files.txt"
    cookie_file = tmp_path / "cookies.txt"
    args = build_args(
        url="https://example.com/post/1",
        cli="--range 2-4",
        download_dir=str(tmp_path / "downloads"),
        template="{id}.{extension}",
        cookie_file=cookie_file,
        manifest_file=manifest,
    )

    assert args[-1] == "https://example.com/post/1"
    assert ["--destination", str(tmp_path / "downloads")] == args[args.index("--destination") : args.index("--destination") + 2]
    assert args.count("--Print-to-file") == 2
    assert str(manifest) in args
    assert "--config-ignore" in args


def test_build_args_rejects_empty_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="url param is required"):
        build_args(url="  ", cli="", download_dir=str(tmp_path))


def test_options_and_shell_command_shape(tmp_path: Path) -> None:
    options = get_options()
    assert VERSION == "1.32.5"
    assert any("--range" in entry["flags"] and not entry["ignored"] for entry in options)
    assert any("--destination" in entry["flags"] and entry["ignored"] for entry in options)

    command, details = build_shell_command(
        {"url": "https://example.com/post/1", "folder": "gallery", "cli": "--range 1"},
        str(tmp_path),
    )
    assert command.startswith("gallery-dl ")
    assert details["gallery_dl"]["version"] == "1.32.5"
