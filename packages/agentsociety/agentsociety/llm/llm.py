import asyncio
import os
import random
import time
from enum import Enum
from multiprocessing import cpu_count
from typing import Any, List, Optional, Union, overload

import httpx
import ray
from openai import NOT_GIVEN, APIConnectionError, AsyncOpenAI, NotGiven, OpenAIError
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionToolChoiceOptionParam,
    ChatCompletionToolParam,
    completion_create_params,
)
from pydantic import BaseModel, Field, field_serializer, model_validator

from ..logger import get_logger

os.environ["GRPC_VERBOSITY"] = "ERROR"

__all__ = [
    "LLM",
    "LLMConfig",
    "LLMProviderType",
]

MAX_TIMEOUT = 60

class LLMProviderType(str, Enum):
    """
    Defines the types of LLM providers.
    - **Description**:
        - Enumerates different types of LLM providers.

    - **Types**:
        - `OPENAI`: OpenAI and compatible providers (based on base_url).
        - `DEEPSEEK`: DeepSeek.
        - `QWEN`: Qwen.
        - `ZHIPU`: Zhipu.
        - `SILICONFLOW`: SiliconFlow.
        - `VLLM`: VLLM.
        - `OLLAMA`: Ollama local inference server.
    """

    OpenAI = "openai"
    DeepSeek = "deepseek"
    Qwen = "qwen"
    ZhipuAI = "zhipuai"
    SiliconFlow = "siliconflow"
    VolcEngine = "volcengine"
    VLLM = "vllm"
    Ollama = "ollama"


class LLMConfig(BaseModel):
    """LLM configuration class."""

    provider: LLMProviderType = Field(...)
    """The type of the LLM provider"""

    base_url: Optional[str] = Field(None)
    """The base URL for the LLM provider"""

    api_key: str = Field(...)
    """API key for accessing the LLM provider"""

    model: str = Field(...)
    """The model to use"""

    concurrency: int = Field(200, ge=1)
    """Concurrency value for LLM operations to avoid rate limit"""

    timeout: float = Field(30, ge=1, le=MAX_TIMEOUT)
    """Timeout for LLM operations in seconds"""

    @field_serializer("provider")
    def serialize_provider(self, provider: LLMProviderType, info):
        return provider.value

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.provider not in (LLMProviderType.VLLM, LLMProviderType.Ollama) and self.base_url is not None:
            raise ValueError("base_url is not supported for this provider")
        return self


@ray.remote
class LLMActor:
    """
    Actor class for LLM operations.
    """

    def __init__(self):
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=min(30.0, MAX_TIMEOUT / 4),  # 连接超时时间
                read=MAX_TIMEOUT,  # 读取超时时间
                write=MAX_TIMEOUT,  # 写入超时时间
                pool=MAX_TIMEOUT,  # 连接池超时时间
            ),
            limits=httpx.Limits(
                max_keepalive_connections=20, max_connections=100, keepalive_expiry=30.0
            ),
        )

    async def call(
        self,
        config: LLMConfig,
        dialog: list[ChatCompletionMessageParam],
        response_format: Union[
            completion_create_params.ResponseFormat, NotGiven
        ] = NOT_GIVEN,
        temperature: float = 1,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 300,
        retries: int = 10,
        tools: Union[List[ChatCompletionToolParam], NotGiven] = NOT_GIVEN,
        tool_choice: Union[ChatCompletionToolChoiceOptionParam, NotGiven] = NOT_GIVEN,
    ):
        """
        Sends an asynchronous text request to the configured LLM API.

        - **Description**:
            - Attempts to send a text request up to `retries` times with exponential backoff on failure.
            - Handles different request types and manages token usage statistics.

        - **Args**:
            - `config`: LLM configuration.
            - `dialog`: Messages to send as part of the chat completion request.
            - `response_format`: JSON schema for the response. Default is NOT_GIVEN.
            - `temperature`: Controls randomness in the model's output. Default is 1.
            - `max_tokens`: Maximum number of tokens to generate in the response. Default is None.
            - `top_p`: Limits the next token selection to a subset of tokens with a cumulative probability above this value. Default is None.
            - `frequency_penalty`: Penalizes new tokens based on their existing frequency in the text so far. Default is None.
            - `presence_penalty`: Penalizes new tokens based on whether they appear in the text so far. Default is None.
            - `timeout`: Request timeout in seconds. Default is 300 seconds.
            - `retries`: Number of retry attempts in case of failure. Default is 10.
            - `tools`: List of dictionaries describing the tools that can be called by the model. Default is NOT_GIVEN.
            - `tool_choice`: Dictionary specifying how the model should choose from the provided tools. Default is NOT_GIVEN.

        - **Returns**:
            - A string containing the message content or a dictionary with tool call arguments if tools are used.
            - Raises exceptions if the request fails after all retry attempts.
        """
        start_time = time.time()

        log = {
            "request_time": start_time,
            "total_errors": 0,
            "error_types": {
                "connection_error": 0,
                "openai_error": 0,
                "timeout_error": 0,
                "other_error": 0,
            },
            "input_tokens": 0,
            "output_tokens": 0,
        }

        client = AsyncOpenAI(
            api_key=config.api_key,
            timeout=config.timeout,
            base_url=config.base_url,
            http_client=self._http_client,
        )
        for attempt in range(retries):
            response = None
            try:
                response = await client.chat.completions.create(
                    model=config.model,
                    messages=dialog,
                    response_format=response_format,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    top_p=top_p,
                    frequency_penalty=frequency_penalty,
                    presence_penalty=presence_penalty,
                    stream=False,
                    timeout=timeout,
                    tools=tools,
                    tool_choice=tool_choice,
                )
                if response.usage is not None:
                    log["input_tokens"] += response.usage.prompt_tokens
                    log["output_tokens"] += response.usage.completion_tokens
                else:
                    get_logger().warning(f"No usage in response: {response}")
                end_time = time.time()
                log["consumption"] = end_time - start_time
                if tools:
                    return response, log
                else:
                    content = response.choices[0].message.content
                    if content is None:
                        raise ValueError("No content in response")
                    return content, log
            except APIConnectionError as e:
                get_logger().warning(
                    f"API connection error: `{e}` for request {dialog} {tools} {tool_choice}. original response: `{response}`. Retry {attempt+1} of {retries}"
                )
                log["total_errors"] += 1
                log["error_types"]["connection_error"] += 1
                if attempt < retries - 1:
                    time.sleep(random.random() * 2**attempt)
                else:
                    raise e
            except OpenAIError as e:
                error_message = str(e)
                get_logger().warning(
                    f"OpenAIError: {error_message} for request {dialog} {tools} {tool_choice}. original response: `{response}`. Retry {attempt+1} of {retries}"
                )
                log["total_errors"] += 1
                log["error_types"]["openai_error"] += 1
                if attempt < retries - 1:
                    time.sleep(random.random() * 2**attempt)
                else:
                    raise e
            except asyncio.TimeoutError as e:
                get_logger().warning(
                    f"TimeoutError: `{e}` for request {dialog} {tools} {tool_choice}. original response: `{response}`. Retry {attempt+1} of {retries}"
                )
                log["total_errors"] += 1
                log["error_types"]["timeout_error"] += 1
                if attempt < retries - 1:
                    time.sleep(random.random() * 2**attempt)
                else:
                    raise e
            except Exception as e:
                get_logger().warning(
                    f"LLM Error: `{e}` for request {dialog} {tools} {tool_choice}. original response: `{response}`. Retry {attempt+1} of {retries}"
                )
                log["total_errors"] += 1
                log["error_types"]["other_error"] += 1
                if attempt < retries - 1:
                    time.sleep(random.random() * 2**attempt)
                else:
                    raise e
        raise RuntimeError("Failed to get response from LLM")


class LLM:
    """
    Main class for the Large Language Model (LLM) object used by Agent(Soul).

    - **Description**:
        - This class manages configurations and interactions with different large language model APIs.
        - It initializes clients based on the specified request type and handles token usage and consumption reporting.
    """

    def __init__(self, configs: List[LLMConfig], num_actors: int = min(cpu_count(), 8)):
        """
        Initializes the LLM instance.

        - **Parameters**:
            - `configs`: An instance of `LLMConfig` containing configuration settings for the LLM.
            - `num_actors` (`int`): Number of actor instances to create for parallel processing. Defaults to min(cpu_count(), 8).
        """

        if len(configs) == 0:
            raise ValueError(
                "No LLM config is provided, please check your configuration"
            )

        self.configs = configs
        self._semaphores = [
            asyncio.Semaphore(config.concurrency) for config in self.configs
        ]
        self._log_list = []
        self.prompt_tokens_used = 0
        self.completion_tokens_used = 0
        self._next_index = 0
        self._last_show_time = time.time()

        for config in self.configs:
            base_url = config.base_url
            if base_url is not None:
                base_url = base_url.rstrip("/")

            if config.provider == LLMProviderType.OpenAI:
                ...
            elif config.provider == LLMProviderType.DeepSeek:
                base_url = "https://api.deepseek.com/v1"
            elif config.provider == LLMProviderType.Qwen:
                base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            elif config.provider == LLMProviderType.SiliconFlow:
                base_url = "https://api.siliconflow.cn/v1"
            elif config.provider == LLMProviderType.VLLM:
                ...
            elif config.provider == LLMProviderType.Ollama:
                if base_url is None:
                    base_url = "http://localhost:11434/v1"
            elif config.provider == LLMProviderType.ZhipuAI:
                base_url = "https://open.bigmodel.cn/api/paas/v4/"
            elif config.provider == LLMProviderType.VolcEngine:
                base_url = "https://ark.cn-beijing.volces.com/api/v3/"
            else:
                raise ValueError(f"Unsupported `provider` {config.provider}!")
            config.base_url = base_url

        self._actors = [LLMActor.remote() for _ in range(num_actors)]
        self._lock = asyncio.Lock()

    def get_log_list(self):
        return self._log_list

    def clear_log_list(self):
        self._log_list = []

    def _get_index(self):
        self._next_index += 1
        return self._next_index

    @overload
    async def atext_request(
        self,
        dialog: list[ChatCompletionMessageParam],
        response_format: Union[
            completion_create_params.ResponseFormat, NotGiven
        ] = NOT_GIVEN,
        temperature: float = 1,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 300,
        retries: int = 10,
        tools: NotGiven = NOT_GIVEN,
        tool_choice: NotGiven = NOT_GIVEN,
    ) -> str: ...

    @overload
    async def atext_request(
        self,
        dialog: list[ChatCompletionMessageParam],
        response_format: Union[
            completion_create_params.ResponseFormat, NotGiven
        ] = NOT_GIVEN,
        temperature: float = 1,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 300,
        retries: int = 10,
        tools: List[ChatCompletionToolParam] = [],
        tool_choice: ChatCompletionToolChoiceOptionParam = "auto",
    ) -> Any: ...

    async def atext_request(
        self,
        dialog: list[ChatCompletionMessageParam],
        response_format: Union[
            completion_create_params.ResponseFormat, NotGiven
        ] = NOT_GIVEN,
        temperature: float = 1,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 300,
        retries: int = 10,
        tools: Union[List[ChatCompletionToolParam], NotGiven] = NOT_GIVEN,
        tool_choice: Union[ChatCompletionToolChoiceOptionParam, NotGiven] = NOT_GIVEN,
    ):
        """
        Sends an asynchronous text request to the configured LLM API.

        - **Description**:
            - Attempts to send a text request up to `retries` times with exponential backoff on failure.
            - Handles different request types and manages token usage statistics.

        - **Args**:
            - `dialog`: Messages to send as part of the chat completion request.
            - `response_format`: JSON schema for the response. Default is NOT_GIVEN.
            - `temperature`: Controls randomness in the model's output. Default is 1.
            - `max_tokens`: Maximum number of tokens to generate in the response. Default is None.
            - `top_p`: Limits the next token selection to a subset of tokens with a cumulative probability above this value. Default is None.
            - `frequency_penalty`: Penalizes new tokens based on their existing frequency in the text so far. Default is None.
            - `presence_penalty`: Penalizes new tokens based on whether they appear in the text so far. Default is None.
            - `timeout`: Request timeout in seconds. Default is 300 seconds.
            - `retries`: Number of retry attempts in case of failure. Default is 10.
            - `tools`: List of dictionaries describing the tools that can be called by the model. Default is NOT_GIVEN.
            - `tool_choice`: Dictionary specifying how the model should choose from the provided tools. Default is NOT_GIVEN.

        - **Returns**:
            - A string containing the message content or a dictionary with tool call arguments if tools are used.
            - Raises exceptions if the request fails after all retry attempts.
        """
        index = self._get_index()
        client_i = index % len(self.configs)
        actor_i = index % len(self._actors)
        if time.time() - self._last_show_time > 10:
            get_logger().info(
                f"LLM request count: {index}"
            )
            self._last_show_time = time.time()
        async with self._semaphores[client_i]:
            content, log = await self._actors[actor_i].call.remote(  # type: ignore
                self.configs[client_i],
                dialog,
                response_format,
                temperature,
                max_tokens,
                top_p,
                frequency_penalty,
                presence_penalty,
                timeout,
                retries,
                tools,
                tool_choice,
            )
            self._log_list.append(log)
            self.prompt_tokens_used += log["input_tokens"]
            self.completion_tokens_used += log["output_tokens"]
        return content
