"""同源托管前端：P0 示例页优先，避免再打开统一知识助手的构建产物。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# 旧前端会停在这些地址。直接返回示例页，不要 302 回 `/`，否则浏览器会继续用缓存里的统一知识助手。
_LEGACY_PAGE_PATHS = ("/login", "/qa")
_DEMO_HEADERS = {
    "Cache-Control": "no-store",
    "Clear-Site-Data": '"cache"',
}

APP_DIR = Path(__file__).resolve().parent
SPA_DIR = APP_DIR.parent / "frontend" / "dist"
DEMO_INDEX = APP_DIR.parent / "frontend" / "index.html"
WIDGET_SCRIPT = APP_DIR.parent / "frontend" / "widget.js"


def _demo_page() -> FileResponse:
    return FileResponse(
        DEMO_INDEX,
        media_type="text/html; charset=utf-8",
        headers=_DEMO_HEADERS,
    )


def register_frontend(app: FastAPI) -> None:
    """有 P0 示例页就托管它。只有示例页缺失时才回退到 frontend/dist。"""
    if WIDGET_SCRIPT.is_file():
        @app.get("/widget.js", include_in_schema=False)
        def widget_script() -> FileResponse:
            return FileResponse(WIDGET_SCRIPT, media_type="text/javascript; charset=utf-8")

    if DEMO_INDEX.is_file():
        app.get("/")(_demo_page)
        for legacy_path in _LEGACY_PAGE_PATHS:
            app.get(legacy_path, include_in_schema=False)(_demo_page)
        return

    spa_index = SPA_DIR / "index.html"
    if spa_index.is_file():
        assets_dir = SPA_DIR / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="spa-assets")

        @app.get("/")
        def spa_root() -> FileResponse:
            return FileResponse(spa_index)

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            spa_root_dir = SPA_DIR.resolve()
            candidate = (spa_root_dir / full_path).resolve()
            if candidate.is_file() and (candidate == spa_root_dir or spa_root_dir in candidate.parents):
                return FileResponse(candidate)
            return FileResponse(spa_index)

        return

    @app.get("/")
    def spa_missing() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "未找到前端页面。请确认 frontend/index.html 存在，或在 frontend/ 执行 npm run build。"
            },
        )
