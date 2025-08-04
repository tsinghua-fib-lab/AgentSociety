# Prerequisites

Before starting your first simulation, please ensure your environment meets the following prerequisites.

## Hardware Requirements

- Memory: At least 12GB **available** memory, 32GB is recommended.
- CPU: >= 4 cores

## Supported Platforms

- Linux x86
- macOS ARM
- Windows Subsystem for Linux (WSL) 2 x86

Python 3.11 or higher is required.

## LLM API

To use this framework, you **need access to LLM APIs**. We support multiple providers:

- [DeepSeek](https://deepseek.com/)
- [OpenAI](https://openai.com/)
- [Qwen](https://tongyi.aliyun.com/)
- [SiliconFlow](https://siliconflow.cn/)
- [ZhipuAI](https://chatglm.cn/)
- [VolcEngine](https://www.volcengine.com/)
- [vLLM](https://docs.vllm.ai/en/stable/)
- [Ollama](https://ollama.ai/)

Actually, the `vLLM` means any LLM inference engine with the [OpenAI API](https://platform.openai.com/docs/api-reference/introduction)-compatible interface.
You can set the `base_url` and `api_key` in the `llm` section of the configuration to connect to any LLM inference engine or provider.

### Free Models

As a simple example, you can use GLM-4-Flash, the free model provided by Zhipu.

Here is how to obtain the ZhipuAI API:
1. Visit [https://open.bigmodel.cn/](https://open.bigmodel.cn/)
2. Register an account and authorize yourself at [https://open.bigmodel.cn/usercenter/settings/auth/](https://open.bigmodel.cn/usercenter/settings/auth/)
3. Create an API key of `GLM-4-Flash` (free model) at [https://open.bigmodel.cn/usercenter/apikeys/](https://open.bigmodel.cn/usercenter/apikeys/)

As shown in the figure below, you will have successfully acquired an API key.

![Zhipu API](../_static/01-llm-api.png)

### Self-hosted Models by vLLM

vLLM is a high-performance LLM inference engine that supports distributed inference and model parallelism.
You can use it to self-host your own LLM models for AgentSociety.

Here is how to install vLLM:

1. build a virtual environment (python >= 3.9) and activate it.

```bash
python -m venv .venv
source .venv/bin/activate
```

2. install vLLM (waiting for long time).

```bash
pip install vllm
```

3. run the following command to start the vLLM server.
```bash
vllm serve \
    --host 0.0.0.0 \
    --port $PORT \
    --api-key $API_KEY \
    --enable-auto-tool-choice \
    --tool-call-parser $TOOL_CALL_PARSER \
    --guided-decoding-backend outlines \
    $MODEL_NAME
```
- `$PORT`: the port of the vLLM server, change it to any available port
- `$API_KEY`: the api key of the vLLM server, change it to any string. If you don't want to make the server authenticated, you can delete the `--api-key $API_KEY` argument. (**Warning**: Please be aware of the security risk if you do this.)
- `$MODEL_NAME` and `$TOOL_CALL_PARSER`: the name of the model to use and the tool-call parser to use, change it to the name of the model you want to use and the tool-call parser you want to use. We have tested `Qwen/Qwen2.5-7B-Instruct` with tool-call-parser (`hermes`) and it works well.

```{admonition} Danger
:class: danger
Unless you know what you're doing, always set API_KEY to complex random text to avoid the security risk.
```

```{admonition} Important
:class: important
Please make sure the vLLM server enables the `enable-auto-tool-choice` and `tool-call-parser` options.
You can refer to the [vLLM's official documentation](https://docs.vllm.ai/en/stable/features/tool_calling.html#automatic-function-calling) to find out the relation between the tool call parsers and the models.
```

```{admonition} Important
:class: important
Select the guided decoding backend as `outlines`.
Otherwise, you will see the AgentSociety failed when using the default cityagent.
```

You can also use the `CUDA_VISIBLE_DEVICES` environment variable to specify the GPU ID.

You should set the `HF_ENDPOINT` environment to `https://hf-mirror.com` to avoid the model download problem if you are in China.

After the vLLM server is running, you can set the `base_url` as the address of the vLLM server with path `/v1` (e.g. `http://your-server-ip:$PORT/v1`) to use it.

### Self-hosted Models by Ollama

Ollama is a lightweight, easy-to-use LLM inference engine that supports running models locally.
You can use it to self-host your own LLM models for AgentSociety with minimal setup.

Here is how to install and run Ollama:

1. Install Ollama by following the instructions at [https://ollama.ai/](https://ollama.ai/)

2. Download a model (e.g., Llama 2):
```bash
ollama pull llama2
```

3. Start the Ollama server:
```bash
ollama serve
```

4. The server will run on `http://localhost:11434` by default, with OpenAI-compatible API available at `http://localhost:11434/v1`

```{admonition} Important
:class: important
Ollama provides an OpenAI-compatible API endpoint at `/v1` which works seamlessly with AgentSociety.
You don't need to set an API key when using Ollama locally, but you must provide a dummy value in the configuration.
```

```{admonition} Note
:class: note
You can run Ollama on a different host or port by setting environment variables or command-line options.
See the Ollama documentation for more details on advanced configuration.
```

After Ollama is running, you can use it in AgentSociety by setting `provider: "ollama"` in your configuration.
