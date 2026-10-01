from functools import lru_cache
from typing import Literal

Engine = Literal["auto", "ytdlp", "gallerydl"]
ENGINES = ("auto", "ytdlp", "gallerydl")
# These sources primarily expose images and collections, even when yt-dlp has
# a video extractor for the same URL. Users can override either engine.
IMAGE_SITES = frozenset(
    {
        "vsco",
        "pixiv",
        "danbooru",
        "e621",
        "deviantart",
        "flickr",
        "imgur",
        "mangadex",
        "gelbooru",
        "sankaku",
        "kemono",
        "coomer",
        "booru",
        "directlink",
        "imagehost",
    }
)


@lru_cache(maxsize=2048)
def gallerydl_matches(url: str) -> dict | None:
    from gallery_dl import extractor

    found = extractor.find(url)
    if found is None:
        return None
    return {"category": found.category, "subcategory": found.subcategory, "basecategory": found.basecategory}


def resolve_engine(url: str, engine: str = "auto", preset=None, extras: dict | None = None, config=None) -> str:
    from app.library.config import Config

    if engine not in ENGINES:
        msg = "Engine must be auto, ytdlp, or gallerydl."
        raise ValueError(msg)
    config = config or Config.get_instance()
    selected = engine if engine != "auto" else getattr(preset, "engine", "auto")
    if selected == "gallerydl" and not config.gallerydl_enabled:
        msg = "The gallery-dl engine is disabled."
        raise ValueError(msg)
    if selected != "auto":
        return selected
    if not config.gallerydl_enabled or not config.gallerydl_auto:
        return "ytdlp"
    match = gallerydl_matches(url)
    if not match:
        return "ytdlp"
    category = match["category"]
    excluded = {s.strip().lower() for s in config.gallerydl_exclude_sites.split(",")}
    if category in excluded:
        return "ytdlp"
    preferred = {s.strip().lower() for s in config.gallerydl_sites.split(",")}
    if (
        category in preferred
        or category in IMAGE_SITES
        or match["basecategory"] in IMAGE_SITES
        or (extras or {}).get("engine_preference") == "gallerydl"
    ):
        return "gallerydl"
    from app.features.ytdlp.utils import get_archive_id

    found = get_archive_id(url)
    return (
        "ytdlp"
        if found.get("ie_key") and found["ie_key"].lower() not in {"generic", "html5mediaembed"}
        else "gallerydl"
    )
