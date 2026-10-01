from aiohttp import web

from app.features.core.utils import api_error_response
from app.features.downloads.items import Item
from app.library.encoder import Encoder
from app.library.router import route

from .extractor import extract
from .opts import _invalid, build_options, gallerydl_arg_converter


@route("POST", "api/gallery-dl/detect/")
async def detect(request):
    from app.features.presets.service import Presets

    from .detect import resolve_engine

    try:
        data = await request.json()
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            msg = "URL is required."
            _invalid(msg)
        engine = resolve_engine(
            url, data.get("engine", "auto"), Presets.get_instance().get(data.get("preset", "")), data.get("extras")
        )
        return web.json_response({"engine": engine})
    except (TypeError, ValueError) as exc:
        return api_error_response(str(exc), code="INVALID", status=400)


@route("GET", "api/gallery-dl/options/")
async def options(request, encoder: Encoder):  # noqa: ARG001
    from gallery_dl import option

    parser = option.build_parser()
    return web.json_response(
        {
            "options": [
                {
                    "flags": action.option_strings,
                    "name": action.dest,
                    "help": action.help,
                    "choices": list(action.choices) if action.choices else None,
                }
                for action in parser._actions
                if action.option_strings
            ],
            "template": "{field}",
            "documentation": "https://gdl-org.github.io/docs/configuration.html",
        },
        dumps=encoder.encode,
    )


@route("GET", "api/gallery-dl/extractors/")
async def extractors(request, encoder: Encoder):  # noqa: ARG001
    from gallery_dl import extractor

    return web.json_response(
        [
            {"category": cls.category, "subcategory": cls.subcategory, "pattern": cls.pattern}
            for cls in extractor.extractors()
        ],
        dumps=encoder.encode,
    )


@route("POST", "api/gallery-dl/convert/")
async def convert(request, encoder: Encoder):
    try:
        data = await request.json()
        raw = data.get("args", data.get("cli", ""))
        if not isinstance(raw, str):
            msg = "Options must be a string."
            _invalid(msg)
        return web.json_response({"options": gallerydl_arg_converter(raw)}, dumps=encoder.encode)
    except (ValueError, TypeError) as exc:
        return api_error_response(str(exc), code="INVALID", status=400)


@route("GET", "api/gallery-dl/url/info/")
@route("POST", "api/gallery-dl/url/info/")
async def url_info(request, encoder: Encoder):
    try:
        data = dict(request.query) if request.method == "GET" else await request.json()
        item = Item.format({**data, "engine": "gallerydl"})
        limit = int(data.get("limit", 0))
        if limit < 0:
            msg = "limit must be non-negative."
            _invalid(msg)
        info = await extract(
            item.url, build_options(item), resolve=str(data.get("resolve", "false")).lower() == "true", limit=limit
        )
        return web.json_response(info, dumps=encoder.encode)
    except Exception as exc:
        return api_error_response(str(exc), code="INVALID", status=400)


@route("GET", "api/gallery-dl/version/")
async def version(request):  # noqa: ARG001
    from gallery_dl import __version__

    from app.library.config import Config

    return web.json_response({"version": __version__, "new_version": Config.get_instance().gallerydl_new_version})


@route("POST", "api/gallery-dl/options/")
async def compiled_options(request, encoder: Encoder):
    try:
        data = await request.json()
        item = Item.format({**data, "engine": "gallerydl"})
        return web.json_response({"options": build_options(item)}, dumps=encoder.encode)
    except (TypeError, ValueError) as exc:
        return api_error_response(str(exc), code="INVALID", status=400)
