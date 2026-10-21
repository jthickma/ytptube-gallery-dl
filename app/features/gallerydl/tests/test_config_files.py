import copy
import json

import pytest
from gallery_dl import config as gallery_config

from app.features.gallerydl.opts import apply_options


@pytest.fixture(autouse=True)
def clear_gallery_config():
    gallery_config.clear()
    yield
    gallery_config.clear()


def test_config_file_site_settings_survive_app_defaults_and_item_overrides(tmp_path):
    config_file = tmp_path / "gallery-dl.json"
    config_file.write_text(
        json.dumps(
            {
                "extractor": {
                    "retries": 7,
                    "vsco": {"username": "fixture", "videos": False, "retries": 2},
                    "pixiv": {"refresh-token": "fixture-token"},
                },
                "downloader": {"http": {"rate": 123}},
            }
        )
    )
    options = {
        "_config_files": [str(config_file)],
        "extractor": {
            "archive": str(tmp_path / "archive.sqlite3"),
            "timeout": 30,
            "vsco": {"videos": True},
        },
        "output": {"mode": "null"},
    }
    original = copy.deepcopy(options)

    apply_options(options)

    assert gallery_config.get(("extractor", "vsco"), "username") == "fixture"
    assert gallery_config.get(("extractor", "vsco"), "videos") is True
    assert gallery_config.get(("extractor", "vsco"), "retries") == 2
    assert gallery_config.get(("extractor", "pixiv"), "refresh-token") == "fixture-token"
    assert gallery_config.get(("extractor",), "retries") == 7
    assert gallery_config.get(("extractor",), "timeout") == 30
    assert gallery_config.get(("extractor",), "archive") == str(tmp_path / "archive.sqlite3")
    assert gallery_config.get(("downloader", "http"), "rate") == 123
    assert options == original


def test_config_file_lists_and_scalar_values_are_replaced_by_explicit_options(tmp_path):
    config_file = tmp_path / "gallery-dl.json"
    config_file.write_text(json.dumps({"extractor": {"postprocessors": ["metadata"], "retries": 2, "vsco": False}}))

    apply_options(
        {
            "_config_files": [str(config_file)],
            "extractor": {"postprocessors": ["zip"], "retries": 5, "vsco": {"videos": True}},
        }
    )

    assert gallery_config.get(("extractor",), "postprocessors") == ["zip"]
    assert gallery_config.get(("extractor",), "retries") == 5
    assert gallery_config.get(("extractor", "vsco"), "videos") is True
