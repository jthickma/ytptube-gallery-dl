from aiohttp import web
from aiohttp.web import Request, Response

from app.library.config import Config
from app.library.encoder import Encoder
from app.library.router import route

from .utils import VERSION, build_shell_command, get_options, parse_cli


@route("GET", "api/gallery-dl/options/", "gallerydl.options")
async def gallerydl_options() -> Response:
    return web.json_response(data={"version": VERSION, "options": get_options()})


@route("POST", "api/gallery-dl/convert/", "gallerydl.convert")
async def gallerydl_convert(request: Request) -> Response:
    data = await request.json()
    try:
        args = parse_cli(str(data.get("args") or ""))
    except ValueError as exc:
        return web.json_response(data={"error": str(exc)}, status=web.HTTPBadRequest.status_code)
    return web.json_response(data={"args": args})


@route("POST", "api/gallery-dl/command/", "gallerydl.command")
async def gallerydl_command(request: Request, config: Config, encoder: Encoder) -> Response:
    if not config.console_enabled:
        return web.json_response(data={"error": "Console is disabled."}, status=web.HTTPForbidden.status_code)
    data = await request.json()
    try:
        command, details = build_shell_command(data, config.download_path)
    except Exception as exc:
        return web.json_response(data={"error": str(exc)}, status=web.HTTPBadRequest.status_code)
    if request.query.get("full", False):
        return web.json_response(data=details, dumps=encoder.encode)
    return web.json_response(data={"command": command})
