"""Swagger 页面外观与静态资源；继续使用 FastAPI 的原生 Swagger 引导。"""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

_TAG_LABELS = {
    "service": "服务状态",
    "modules": "智能体与环境",
    "prefill-params": "预填充参数",
    "custom": "自定义模块",
    "agent-skills": "行为技能",
    "experiments": "实验与产物",
    "replay": "回放数据",
}


def render_swagger_page(
    app: FastAPI,
    root_path: str = "",
    *,
    swagger_js_url: str | None = None,
    swagger_css_url: str | None = None,
) -> HTMLResponse:
    """按实际服务前缀生成页面，预览可复用本地 Swagger 资源。"""
    prefix = root_path.rstrip("/") or "."
    assets = prefix + "/docs-assets"
    redirect = app.swagger_ui_oauth2_redirect_url
    response = get_swagger_ui_html(
        openapi_url=prefix + (app.openapi_url or "/openapi.json"),
        title=escape(f"{app.title} · Swagger"),
        swagger_js_url=swagger_js_url or assets + "/swagger-ui-bundle.js",
        swagger_css_url=swagger_css_url or assets + "/swagger-ui.css",
        swagger_favicon_url="data:,",
        oauth2_redirect_url=root_path.rstrip("/") + redirect if redirect else None,
        init_oauth=app.swagger_ui_init_oauth,
        swagger_ui_parameters=app.swagger_ui_parameters,
    )
    asset_url = escape(assets, quote=True)
    redoc_url = escape(prefix + (app.redoc_url or "/redoc"), quote=True)
    spec_url = escape(prefix + (app.openapi_url or "/openapi.json"), quote=True)
    tags = app.openapi_tags or []
    navigation = "".join(
        '<a class="api-group-link" href="#/'
        + quote(tag["name"], safe="")
        + '" data-api-tag="'
        + escape(tag["name"], quote=True)
        + '"><span>'
        + escape(_TAG_LABELS.get(tag["name"], tag["name"]))
        + "</span><code>"
        + escape(tag["name"])
        + "</code></a>"
        for tag in tags
    )
    header = f"""
    <a class="api-skip-link" href="#api-main">跳到接口内容</a>
    <header class="api-header">
      <a class="api-brand" href="#"><span>AgentSociety <b>2</b></span>
        <span class="api-version">v{escape(app.version)}</span></a>
      <nav class="api-tools" aria-label="文档视图">
        <span class="api-current" aria-current="page">Swagger</span>
        <a href="{redoc_url}" title="阅读接口与模型说明">ReDoc</a>
        <a href="{spec_url}">OpenAPI <span aria-hidden="true">↗</span></a>
        <button id="api-theme" type="button" aria-label="切换深浅色">深浅色</button>
      </nav>
    </header>
    <div class="api-layout">
      <aside class="api-sidebar"><nav aria-label="接口分组">
        <p class="api-nav-title">接口分组</p>{navigation}
      </nav><p class="api-sidebar-note">Swagger · 交互调试<br>ReDoc · 接口阅读</p></aside>
      <main id="api-main" class="api-main" tabindex="-1">
        <section class="api-hero" aria-labelledby="api-heading">
          <div><p class="api-eyebrow">开发者参考</p><h1 id="api-heading">后端 API</h1>
            <p class="api-lead">查询模块与实验，读取回放，管理自定义技能。</p></div>
          <p class="api-count">{len(tags)} 个功能分组</p>
        </section>
    """
    body = response.body.decode("utf-8")
    body = body.replace("<html>", '<html lang="zh-CN">', 1)
    body = body.replace(
        "</head>",
        f'<link rel="stylesheet" href="{asset_url}/api-docs.css">\n'
        f'<script src="{asset_url}/api-docs.js"></script>\n</head>',
        1,
    )
    body = body.replace("<body>", "<body>" + header, 1)
    body = body.replace("</body>", "</main></div></body>", 1)
    return HTMLResponse(body)


def install_docs_ui(app: FastAPI) -> None:
    """挂载只读页面资源和文档路由，不进入业务 OpenAPI 目录。"""
    if not app.openapi_url:
        return
    app.mount(
        "/docs-assets",
        StaticFiles(
            directory=Path(__file__).with_name("static"),
            packages=[("fastapi_offline", "static")],
        ),
        name="api-doc-assets",
    )

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui(request: Request) -> HTMLResponse:
        return render_swagger_page(app, request.scope.get("root_path", ""))

    @app.get("/redoc", include_in_schema=False, response_class=HTMLResponse)
    async def redoc(request: Request) -> HTMLResponse:
        """从当前服务加载 ReDoc 和接口定义，支持剥离前缀的反向代理。"""
        prefix = request.scope.get("root_path", "").rstrip("/") or "."
        page = get_redoc_html(
            openapi_url=prefix + (app.openapi_url or "/openapi.json"),
            title=escape(f"{app.title} · ReDoc"),
            redoc_js_url=prefix + "/docs-assets/redoc.standalone.js",
            redoc_favicon_url="data:,",
            with_google_fonts=False,
        )
        # ReDoc 的页脚带有远程图标，离线部署保留文字链接即可。
        page.headers["Content-Security-Policy"] = "img-src 'self' data:"
        return page

    if app.swagger_ui_oauth2_redirect_url:
        app.add_api_route(
            app.swagger_ui_oauth2_redirect_url,
            get_swagger_ui_oauth2_redirect_html,
            include_in_schema=False,
        )
