#!/usr/bin/env python
"""启动 AI Social Scientist 后端。

通过 ``python -m agentsociety2.backend.run`` 运行 :mod:`agentsociety2.backend.app`。``BACKEND_HOST``、``BACKEND_PORT`` 与 ``BACKEND_LOG_LEVEL`` 控制监听地址、端口和日志等级；``WORKSPACE_PATH`` 配置允许访问的研究工作区。访问说明见 :doc:`/api/http`。"""

if __name__ == "__main__":
    import argparse
    import os

    import uvicorn
    from dotenv import load_dotenv

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

    # 加载环境变量文件
    load_dotenv()
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

    # 从环境变量读取配置，命令行参数优先
    # 默认仅回环(2026-11-06 审计修复):后端零认证,绑全网卡即 LAN/网页
    # drive-by 可写任意 skill 脚本;需要对外时显式设 BACKEND_HOST=0.0.0.0。
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "8001"))
    log_level = args.log_level or os.getenv("BACKEND_LOG_LEVEL", "info")

    # 如果命令行参数设置了日志等级，更新环境变量以便 app.py 使用
    if args.log_level:
        os.environ["BACKEND_LOG_LEVEL"] = args.log_level

    print("启动 AI Social Scientist Backend API 服务...")
    print(f"服务地址: http://{host}:{port}")
    print(f"API文档: http://{host}:{port}/docs")
    print(f"健康检查: http://{host}:{port}/health")
    print(f"日志等级: {log_level}")
    print("-" * 60)

    uvicorn.run(
        "agentsociety2.backend.app:app",
        host=host,
        port=port,
        reload=False,
        log_level=log_level,
        ws="wsproto",
    )
