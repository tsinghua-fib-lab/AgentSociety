"""AI Social Scientist 的 FastAPI 应用。

注册实验、回放、参数、模块与技能管理路由，并配置应用生命周期、可信主机和浏览器来源检查。服务入口见 :mod:`agentsociety2.backend.run`，HTTP 调用方式见 :doc:`/api/http`。"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from agentsociety2 import __version__
from agentsociety2.backend import api_documentation as _api_documentation
from agentsociety2.backend import docs_ui as _docs_ui
from agentsociety2.backend.routers import (
    agent_skills,
    custom,
    experiments,
    modules,
    prefill_params,
    replay,
)

# 加载环境变量
_project_root = Path(__file__).resolve().parents[2]
load_dotenv(_project_root / ".env")


# 配置标准 logging
def _setup_logging():
    """配置后端服务日志。

    读取环境变量 ``BACKEND_LOG_LEVEL`` ，并初始化 root logger 与相关模块 logger。
    """
    log_level = os.getenv("BACKEND_LOG_LEVEL", "info")
    # 将 uvicorn 的 "trace" 映射到 Python logging 的 "DEBUG"
    python_log_level = "DEBUG" if log_level.lower() == "trace" else log_level.upper()
    level = getattr(logging, python_log_level, logging.INFO)

    # 配置根 logger（如果还没有配置过）
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            force=True,  # Python 3.8+ 支持，强制重新配置
        )
    else:
        # 如果已经配置过，只更新日志等级
        root_logger.setLevel(level)

    # 设置 agentsociety2 相关模块的日志等级
    agentsociety_logger = logging.getLogger("agentsociety2")
    agentsociety_logger.setLevel(level)

    return agentsociety_logger


_setup_logging()
from agentsociety2.logger import get_logger

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 应用生命周期管理（启动/关闭钩子）。"""
    # 启动时执行
    logger.info("AI Social Scientist Backend Service 启动中...")
    logger.info(f"项目根目录: {_project_root}")

    yield

    # 关闭时执行
    logger.info("AI Social Scientist Backend Service 关闭中...")


# 创建FastAPI应用
app = FastAPI(
    title="AI Social Scientist Backend API",
    docs_url=None,
    description=_api_documentation.API_DESCRIPTION,
    openapi_tags=_api_documentation.OPENAPI_TAGS,
    swagger_ui_parameters=_api_documentation.SWAGGER_UI_PARAMETERS,
    version=__version__,
    lifespan=lifespan,
)

# CORS controls response visibility, not whether a simple cross-origin request
# reaches a mutation endpoint. Reject untrusted browser origins before routing.
_LOCAL_ORIGIN = re.compile(
    r"https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]+)?|vscode-webview://[A-Za-z0-9-]+"
)
_ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.getenv("BACKEND_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}


class BrowserOriginMiddleware:
    """拦截不受信任的浏览器请求（包括 form/simple POST 请求）。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            origins = [
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"origin"
            ]
            if origins and (
                len(origins) != 1
                or not (
                    _LOCAL_ORIGIN.fullmatch(origins[0])
                    or origins[0] in _ALLOWED_ORIGINS
                )
            ):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await JSONResponse(
                        {"error": "Untrusted browser origin"}, status_code=403
                    )(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_ALLOWED_ORIGINS),
    allow_origin_regex=_LOCAL_ORIGIN.pattern,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(BrowserOriginMiddleware)
_allowed_hosts = ["127.0.0.1", "localhost", "[::1]"]
_allowed_hosts += [
    host.strip()
    for host in os.getenv("BACKEND_TRUSTED_HOSTS", "").split(",")
    if host.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

# 注册路由（仅保留必要的API）
app.include_router(prefill_params.router)
app.include_router(experiments.router, prefix="/api/v1")
app.include_router(replay.router, prefix="/api/v1")
app.include_router(custom.router)
app.include_router(modules.router)
app.include_router(agent_skills.router)


@app.get("/")
async def root():
    """:returns: 后端服务基本信息与 endpoints 列表。"""
    return {
        "service": "AI Social Scientist Backend API",
        "version": __version__,
        "status": "running",
        "endpoints": {
            "prefill_params": "/api/v1/prefill-params",
            "experiments": "/api/v1/experiments/{hypothesis_id}/{experiment_id}",
            "replay": "/api/v1/replay/{hypothesis_id}/{experiment_id}/*",
            "custom": "/api/v1/custom/*",
            "modules": "/api/v1/modules/*",
            "agent_skills": "/api/v1/agent-skills/*",
        },
    }


@app.get("/health")
async def health_check():
    """:returns: 健康状态。"""
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器。

    :param request: FastAPI 请求对象（用于扩展日志上下文）。
    :param exc: 未捕获异常。
    :returns: 标准化的 500 JSON 响应。
    """
    logger.error(f"未处理的异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal Server Error",
        },
    )


_api_documentation.install_api_documentation(app)
_docs_ui.install_docs_ui(app)


if __name__ == "__main__":
    import argparse

    import uvicorn

    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="启动 AI Social Scientist Backend API 服务"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="设置日志等级 (critical, error, warning, info, debug, trace)",
    )
    args = parser.parse_args()

    # 从环境变量读取配置，命令行参数优先
    # 默认仅回环(2026-11-06 审计修复):后端零认证,绑全网卡即 LAN/网页
    # drive-by 可写任意 skill 脚本;需要对外时显式设 BACKEND_HOST=0.0.0.0。
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "8001"))
    log_level = args.log_level or os.getenv("BACKEND_LOG_LEVEL", "info")

    # 如果命令行参数设置了日志等级，更新环境变量并重新配置日志
    if args.log_level:
        os.environ["BACKEND_LOG_LEVEL"] = args.log_level
        _setup_logging()

    logger.info(f"启动服务器: http://{host}:{port}")
    logger.info(f"日志等级: {log_level}")
    uvicorn.run(
        "agentsociety2.backend.app:app",
        host=host,
        port=port,
        reload=False,  # 生产环境设为False
        log_level=log_level,
        ws="wsproto",
    )
