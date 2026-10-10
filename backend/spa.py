"""托管 Vue 咨询组件构建产物，内部资料管理使用独立入口。"""

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
DEMO_INDEX = SPA_DIR / "index.html"
WIDGET_SCRIPT = SPA_DIR / "widget.js"


def _demo_page() -> FileResponse:
    return FileResponse(
        DEMO_INDEX,
        media_type="text/html; charset=utf-8",
        headers=_DEMO_HEADERS,
    )


def register_frontend(app: FastAPI) -> None:
    """官网页面仅包含咨询入口；/admin 保留独立内部管理页。"""
    frontend_dir = APP_DIR.parent / "frontend"
    @app.get("/consult", include_in_schema=False, response_model=None)
    def standalone_consultation() -> FileResponse | JSONResponse:
        page = frontend_dir / "dist" / "consult.html"
        if not page.is_file() or not WIDGET_SCRIPT.is_file():
            return JSONResponse(status_code=503, content={
                "detail": "未找到独立咨询页构建产物。请在 frontend/ 执行 npm run build。",
            })
        return FileResponse(page, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    if (frontend_dir / "vendor").is_dir():
        app.mount("/vendor", StaticFiles(directory=frontend_dir / "vendor"), name="frontend-vendor")

    @app.get("/answer-format.js", include_in_schema=False)
    def answer_format_script() -> FileResponse:
        return FileResponse(frontend_dir / "answer-format.js", media_type="text/javascript; charset=utf-8")

    @app.get("/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(frontend_dir / "admin.html", media_type="text/html; charset=utf-8", headers=_DEMO_HEADERS)

    @app.get("/admin-documents.js", include_in_schema=False)
    def admin_documents_script() -> FileResponse:
        return FileResponse(frontend_dir / "admin-documents.js", media_type="text/javascript; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    if WIDGET_SCRIPT.is_file():
        @app.get("/widget.js", include_in_schema=False)
        def widget_script() -> FileResponse:
            return FileResponse(WIDGET_SCRIPT, media_type="text/javascript; charset=utf-8")

    if DEMO_INDEX.is_file():
        app.get("/")(_demo_page)
        for legacy_path in _LEGACY_PAGE_PATHS:
            app.get(legacy_path, include_in_schema=False)(_demo_page)
        return

    @app.get("/")
    def spa_missing() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "未找到 Vue 前端构建产物。请在 frontend/ 执行 npm ci 和 npm run build。"
            },
        )
