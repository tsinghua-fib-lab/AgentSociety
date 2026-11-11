"""日志模块 - 提供统一的日志配置和管理。

本模块提供 agentsociety 项目的日志功能：

主要函数
--------

- **get_logger**: 获取 agentsociety logger 单例
- **set_logger_level**: 设置日志级别
- **setup_logging**: 完整的日志配置（控制台 + 文件）
- **setup_litellm_logging**: 配置 LiteLLM 日志集成

特性
----

- 彩色控制台输出（按日志级别着色）
- INFO 级别超长日志自动截断
- 支持文件日志输出
- LiteLLM API 调用日志集成

使用示例::

    from agentsociety2.logger import get_logger, setup_logging

    # 简单使用
    logger = get_logger()
    logger.info("Hello, world!")

    # 完整配置
    setup_logging(log_file="app.log", log_level=logging.DEBUG)
"""

import json
import logging
import os
import sys
import time
from typing import Any, ClassVar

__all__ = [
    "get_logger",
    "set_logger_level",
    "setup_litellm_logging",
    "setup_logging",
]

# 控制台超长日志：仅 INFO 截断（保留前后），其他级别不截断
_HEAD, _TAIL = 180, 180
_MAX_LEN = 500


def _shorten(msg: str, level: int) -> str:
    if level != logging.INFO or len(msg) <= _MAX_LEN:
        return msg
    return msg[:_HEAD] + " ... " + msg[-_TAIL:]


class ColoredFormatter(logging.Formatter):
    """按级别着色，仅 INFO 超长时截断（保留前后）。格式 [HH:MM:SS] LEVEL  msg"""

    # 颜色方案：INFO 用青色减少视觉疲劳，WARNING/ERROR 用亮色提高可见度
    _colors: ClassVar[dict[int, str]] = {
        logging.DEBUG: "\x1b[90m",  # 暗灰，DEBUG 通常量大，弱化
        logging.INFO: "\x1b[36m",  # 青色，大量 INFO 时比绿色更柔和
        logging.WARNING: "\x1b[93m",  # 亮黄，比普通黄更醒目
        logging.ERROR: "\x1b[91m",  # 亮红，比普通红更突出
        logging.CRITICAL: "\x1b[91;1m",  # 粗体亮红，最高优先级
    }
    _reset = "\x1b[0m"

    def __init__(self, fmt: str | None = None, datefmt: str | None = None):
        """初始化 ColoredFormatter

        :param fmt: 日志格式，默认为 "[%(asctime)s] %(levelname)-7s %(message)s"
        :param datefmt: 时间格式，默认为 "%Y-%m-%d %H:%M:%S"
        """
        super().__init__(
            fmt=fmt or "[%(asctime)s] %(levelname)-7s %(message)s",
            datefmt=datefmt or "%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # 保存原始消息
        orig_msg, orig_args = record.msg, record.args
        # 缩短消息
        msg = _shorten(record.getMessage(), record.levelno)
        record.msg, record.args = msg, ()

        # 先使用父类方法格式化（包含时间）
        formatted = super().format(record)

        # 添加颜色
        use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        if use_color:
            color = self._colors.get(record.levelno, "")
            # 为整行添加颜色（时间、级别、消息）
            formatted = color + formatted + self._reset

        # 恢复原始消息
        record.msg, record.args = orig_msg, orig_args
        return formatted


def get_logger():
    """获取 agentsociety logger 单例。

    :returns: :class:`logging.Logger` （name 固定为 ``agentsociety`` ）。
    """
    logger = logging.getLogger("agentsociety")
    # check if there is already a handler, avoid duplicate output
    if not logger.hasHandlers():
        logger.setLevel(logging.INFO)
        # set propagate to False, avoid duplicate output
        logger.propagate = False

        handler = logging.StreamHandler()
        # Use our custom ColoredFormatter
        handler.setFormatter(ColoredFormatter())
        logger.addHandler(handler)
    return logger


def add_file_handler(log_file: str, level: int = logging.INFO) -> None:
    """为 agentsociety logger 添加文件处理器（幂等）。

    :param log_file: 日志文件路径。
    :param level: 日志级别。
    """
    logger = logging.getLogger("agentsociety")

    # 检查是否已经有相同文件的文件处理器
    for handler in logger.handlers:
        if isinstance(
            handler, logging.FileHandler
        ) and handler.baseFilename == os.path.abspath(log_file):
            return  # 已存在，不重复添加

    # 创建日志目录（如果不存在）
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # 创建文件处理器（使用不带颜色的简单格式）
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    # 文件中使用简单格式，不带颜色
    file_formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)


def set_logger_level(level: str):
    """设置 agentsociety logger 的日志级别。

    :param level: 传给 :meth:`logging.Logger.setLevel` 的级别。
    """
    get_logger().setLevel(level)


class LiteLLMLogger:
    """
    Custom logger for LiteLLM that logs prompts, responses, tokens, and timing.

    This class implements the callback interface for LiteLLM to log:
    - Prompts at DEBUG level
    - Responses at INFO level
    - Token usage and timing at INFO level
    """

    def __init__(self):
        self.logger = get_logger()
        self._call_start_times: dict[str, float] = {}

    def log_pre_api_call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ):
        """在 API 调用前记录 prompt（DEBUG）。"""
        # Generate a unique call ID for tracking
        call_id = f"{model}_{int(time.time() * 1000000)}"
        self._call_start_times[call_id] = time.time()

        prompt_text = self._format_messages(messages)
        prompt_text = _shorten(prompt_text, logging.DEBUG)
        self.logger.debug(f"[LiteLLM] {model} | Prompt:\n{prompt_text}")

        # Store call_id in kwargs for later retrieval
        kwargs["_litellm_call_id"] = call_id

    def log_post_api_call(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: float,
        end_time: float,
    ):
        """在 API 调用后记录 response / tokens / timing（INFO）。"""
        duration = end_time - start_time
        model = kwargs.get("model", "unknown")

        # Extract response content
        response_content = self._extract_response_content(response_obj)

        # Extract token usage
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

        if hasattr(response_obj, "usage") and response_obj.usage:
            input_tokens = getattr(response_obj.usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(response_obj.usage, "completion_tokens", 0) or 0
            total_tokens = getattr(response_obj.usage, "total_tokens", 0) or 0
        elif isinstance(response_obj, dict):
            usage = response_obj.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0) or 0
            output_tokens = usage.get("completion_tokens", 0) or 0
            total_tokens = usage.get("total_tokens", 0) or 0

        response_content = _shorten(response_content, logging.INFO)
        self.logger.info(f"[LiteLLM] {model} | Response:\n{response_content}")

        # Prompt-cache hits. Imported lazily: config/ imports this module, so a
        # top-level import here would be circular.
        from agentsociety2.config.llm_dispatcher import extract_cached_tokens

        cached_tokens = extract_cached_tokens(response_obj)

        # Log token usage and timing at INFO level
        self.logger.info(
            f"[LiteLLM] Model: {model} | Tokens - Input: {input_tokens} "
            f"(cached: {cached_tokens}), "
            f"Output: {output_tokens}, Total: {total_tokens} | "
            f"Duration: {duration:.3f}s"
        )

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        """将 messages 格式化为可读字符串。"""
        formatted_parts = []
        for _i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            # Handle different content types
            if isinstance(content, list):
                # Handle content array (e.g., multimodal)
                content_str = json.dumps(content, ensure_ascii=False, indent=2)
            elif isinstance(content, str):
                content_str = content
            else:
                content_str = str(content)

            formatted_parts.append(f"[{role}]: {content_str}")

            # Include tool_calls if present
            if "tool_calls" in msg:
                tool_calls = msg["tool_calls"]
                formatted_parts.append(
                    f"  Tool calls: {json.dumps(tool_calls, ensure_ascii=False, indent=2)}"
                )

        return "\n".join(formatted_parts)

    def _extract_response_content(self, response_obj: Any) -> str:
        """从 LiteLLM 响应对象中提取主要内容文本。"""
        try:
            if hasattr(response_obj, "choices") and response_obj.choices:
                choice = response_obj.choices[0]
                if hasattr(choice, "message"):
                    content = getattr(choice.message, "content", None)
                    if content:
                        return content
                    # Check for tool calls
                    if hasattr(choice.message, "tool_calls"):
                        tool_calls = choice.message.tool_calls
                        if tool_calls:
                            return f"[Tool calls: {len(tool_calls)}]"
            elif isinstance(response_obj, dict):
                choices = response_obj.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    content = message.get("content")
                    if content:
                        return content
                    # Check for tool calls
                    tool_calls = message.get("tool_calls")
                    if tool_calls:
                        return f"[Tool calls: {len(tool_calls)}]"
        except Exception as e:
            return f"[Error extracting response: {e!s}]"

        return "[Empty or unknown response]"


def setup_litellm_logging():
    """配置 LiteLLM 日志集成。

    默认不启用 callbacks（避免部分版本的序列化告警）；可通过环境变量
    ``AGENTSOCIETY_ENABLE_LITELLM_CALLBACKS=1`` 启用。
    """
    try:
        import litellm

        # NOTE:
        # Some LiteLLM versions can emit noisy Pydantic serialization warnings
        # when callback pipelines serialize provider-specific message objects.
        # Keep callback registration disabled by default to avoid that path.
        # If detailed callback logs are needed, enable via env:
        #   AGENTSOCIETY_ENABLE_LITELLM_CALLBACKS=1
        if os.getenv("AGENTSOCIETY_ENABLE_LITELLM_CALLBACKS", "").strip() == "1":
            litellm_logger = LiteLLMLogger()
            litellm.callbacks = [litellm_logger]
        else:
            litellm.callbacks = []

        # Configure litellm's internal logger
        litellm_logging = logging.getLogger("litellm")
        litellm_logging.handlers.clear()
        litellm_logging.propagate = False
        litellm_logging.setLevel(logging.WARNING)

        get_logger().info(
            "LiteLLM logging initialized (callbacks=%s)", litellm.callbacks
        )
    except ImportError:
        get_logger().warning("litellm not available, skipping LiteLLM logging setup")
    except Exception as e:
        get_logger().warning(f"Failed to setup LiteLLM logging: {e}")


def setup_logging(
    log_file: str | None = None,
    log_level: int = logging.INFO,
    log_format: str | None = None,
    console_output: bool = True,
) -> logging.Logger:
    """初始化应用日志（root + agentsociety + LiteLLM）。

    :param log_file: 可选。日志文件路径；为空则只输出到控制台。
    :param log_level: 日志级别。
    :param log_format: 可选。自定义格式化串；为空则使用默认格式。
    :param console_output: 是否输出到控制台。
    :returns: 配置后的 agentsociety logger 实例。
    """
    # Default format
    if log_format is None:
        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    else:
        file_formatter = logging.Formatter(log_format)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    root_logger.handlers.clear()

    # Add file handler if log_file is provided
    if log_file:
        # Create logs directory if needed
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Add console handler if requested
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(ColoredFormatter())
        root_logger.addHandler(console_handler)

    # Configure agentsociety logger
    logger = get_logger()
    logger.setLevel(log_level)
    logger.handlers.clear()
    logger.propagate = False

    # Add handlers to agentsociety logger
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(ColoredFormatter())
        logger.addHandler(console_handler)

    # Setup LiteLLM logging
    setup_litellm_logging()

    # Configure litellm internal logger to avoid duplicate logs
    litellm_logger = logging.getLogger("litellm")
    litellm_logger.setLevel(logging.WARNING)
    litellm_logger.handlers.clear()
    litellm_logger.propagate = False

    return logger
