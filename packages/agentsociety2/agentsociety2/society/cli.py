"""命令行入口：按 ``steps.yaml`` 驱动 :class:`~agentsociety2.society.society.AgentSociety` 实验。

启动前会校验 ``AGENTSOCIETY_LLM_API_KEY`` 以及可供 CodeGenRouter 使用的 coder
相关密钥（可与主密钥相同）。环境与模块发现见 :mod:`agentsociety2.registry` 。
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agentsociety2.config import Config
from agentsociety2.env import EnvBase
from agentsociety2.env.env_router_actor import get_env_router_actor_class
from agentsociety2.env.env_router_proxy import EnvRouterProxy
from agentsociety2.logger import add_file_handler, get_logger, set_logger_level
from agentsociety2.registry import (
    get_registered_agent_modules,
    get_registered_env_modules,
    scan_and_register_custom_modules,
)
from agentsociety2.society.models import (
    AskStep,
    InitConfig,
    InterveneStep,
    QuestionnaireStep,
    RunStep,
    StepsConfig,
)
from agentsociety2.society.questionnaire import Questionnaire
from agentsociety2.society.society import AgentSociety

logger = get_logger()


#: Agent ``kwargs`` keys the CLI splits into the static ``config`` record (the
#: remaining ``kwargs`` become the ``profile``). Must stay in sync with
#: ``ags experiment-config validate`` and with the keys ``AgentBase.restore``
#: reads from ``self._config``. Add a key here whenever an agent gains a new
#: runtime-config field.
AGENT_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "max_react_turns",
        "enable_memory",
        "enable_todo_list",
        "idle_skip_enabled",
        "disabled_skill_ids",
        "default_activated_skill_ids",
        "extra_skill_paths",
    }
)


def _validate_env_early() -> None:
    """早期环境变量验证（在 main 入口处调用）"""
    errors = []

    # 检查主要 LLM API key
    llm_api_key = os.getenv("AGENTSOCIETY_LLM_API_KEY", "")
    if not llm_api_key or not llm_api_key.strip():
        errors.append("AGENTSOCIETY_LLM_API_KEY")

    # 检查 coder LLM（必须有，因为 CodeGenRouter 需要）
    coder_api_key = os.getenv("AGENTSOCIETY_CODER_LLM_API_KEY") or llm_api_key
    if not coder_api_key or not coder_api_key.strip():
        errors.append("AGENTSOCIETY_CODER_LLM_API_KEY (or AGENTSOCIETY_LLM_API_KEY)")

    if errors:
        print("❌ Environment configuration error:", file=sys.stderr)
        for error in errors:
            print(f"  Missing: {error}", file=sys.stderr)
        print(
            "\nPlease configure these in your .env file before running experiments.",
            file=sys.stderr,
        )
        sys.exit(1)


class ExperimentRunner:
    """实验运行器，负责加载配置、创建实例和执行步骤"""

    def __init__(self, run_dir: Path):
        """
        初始化实验运行器

        :param run_dir: run/ 目录路径，作为实验的 HOME 目录。
        """
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # 创建必要的子目录
        self.artifacts_dir = self.run_dir / "artifacts"
        self.artifacts_dir.mkdir(exist_ok=True)

        # 文件路径
        self.pid_file = self.run_dir / "pid.json"

        self.society: AgentSociety | None = None
        self._env_router: Any = None
        self._should_terminate = False

    def _validate_environment(self) -> None:
        """验证所有必需的环境变量，缺漏则报错退出"""
        errors = []

        # 检查主要 LLM 配置
        llm_api_key = os.getenv("AGENTSOCIETY_LLM_API_KEY", "")
        if not llm_api_key or not llm_api_key.strip():
            errors.append(
                "Missing required environment variable: AGENTSOCIETY_LLM_API_KEY"
            )

        # 检查 coder LLM 配置（CodeGenRouter 需要）
        coder_api_key = os.getenv("AGENTSOCIETY_CODER_LLM_API_KEY") or llm_api_key
        if not coder_api_key or not coder_api_key.strip():
            errors.append(
                "Missing required environment variable: AGENTSOCIETY_CODER_LLM_API_KEY or AGENTSOCIETY_LLM_API_KEY"
            )

        # 如果有错误，打印详细信息并退出
        if errors:
            logger.error("Environment validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            print(
                "\n❌ Environment validation failed. Required configuration:",
                file=sys.stderr,
            )
            for error in errors:
                print(f"  ❌ {error}", file=sys.stderr)
            print(
                "\nPlease set the required environment variables in your .env file.",
                file=sys.stderr,
            )
            sys.exit(1)

        logger.info("Environment validation passed")

    def _load_config(self, config_path: Path) -> InitConfig:
        """加载并验证配置文件"""
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            if config_path.suffix.lower() == ".json":
                data = json.load(f)
            elif config_path.suffix.lower() in [".yaml", ".yml"]:
                data = yaml.safe_load(f)
            else:
                raise ValueError(
                    f"Unsupported config file format: {config_path.suffix}"
                )

        # 使用pydantic验证配置
        try:
            return InitConfig.model_validate(data)
        except Exception as e:
            raise ValueError(f"Invalid config file format: {e}") from e

    def _load_steps(self, steps_path: Path) -> StepsConfig:
        """加载并验证 steps.yaml"""
        if not steps_path.exists():
            raise FileNotFoundError(f"Steps file not found: {steps_path}")

        with open(steps_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 使用pydantic验证配置
        try:
            return StepsConfig.model_validate(data)
        except Exception as e:
            raise ValueError(f"Invalid steps.yaml format: {e}") from e

    def _create_env_modules(
        self, env_module_types: list[str], env_kwargs: dict[str, dict[str, Any]]
    ) -> list[EnvBase]:
        """创建环境模块实例"""
        env_modules = []
        env_type_map = {
            module_type: env_class
            for module_type, env_class in get_registered_env_modules()
        }

        for module_type in env_module_types:
            if module_type not in env_type_map:
                raise ValueError(
                    f"Environment module type '{module_type}' not found in registry. "
                    f"Available types: {list(env_type_map.keys())}"
                )

            env_class = env_type_map[module_type]
            module_kwargs = env_kwargs.get(module_type, {})
            env_module = env_class(**module_kwargs)
            env_modules.append(env_module)

        return env_modules

    def _build_agent_specs(
        self,
        agent_args: list[dict[str, Any]],
    ) -> tuple[list[dict], str]:
        """构建 record-based agent spec(不实例化任何 agent 对象)。

        产出 ``{"id", "profile", "config"}`` spec;``AgentSociety`` 随后经
        ``create_agents_batch`` Ray Task 批量建 workspace,agent 在
        step/query 任务内按需重建(``from_workspace``)。

        agent 类从 registry 解析,并校验全种群唯一(流式模型假设单一
        agent 类——常见形态)。

        :param agent_args: 逐 agent 配置 dict(``agent_id`` / ``agent_type`` /
            ``kwargs``)。
        :returns: ``(agent_specs, agent_class_name)`` 。
        """
        agent_type_map = {
            agent_type: agent_class
            for agent_type, agent_class in get_registered_agent_modules()
        }

        specs: list[dict] = []
        class_names: set[str] = set()
        for agent_arg in agent_args:
            agent_type = agent_arg.get("agent_type")
            agent_id = agent_arg.get("agent_id")

            if not agent_type:
                raise ValueError(f"Agent config missing agent_type: {agent_arg}")
            if agent_id is None:
                raise ValueError(f"Agent config missing agent_id: {agent_arg}")
            if agent_type not in agent_type_map:
                raise ValueError(
                    f"Agent type '{agent_type}' not found in registry. "
                    f"Available types: {list(agent_type_map.keys())}"
                )
            if "kwargs" not in agent_arg:
                raise ValueError(f"Agent config missing 'kwargs' field: {agent_arg}")

            agent_class = agent_type_map[agent_type]
            class_names.add(agent_class.__name__)

            kwargs = dict(agent_arg["kwargs"] or {})
            agent_id_int = int(kwargs.get("id", agent_id))
            kwargs["id"] = agent_id_int

            # profile = all kwargs except config-ish keys; config = the agent's
            # static config fields (see PersonAgent.init_description). For
            # PersonAgent, config keys are max_react_turns / enable_todo_list /
            # enable_memory / etc. We extract recognized config keys out of kwargs
            # if present, defaulting the rest.
            config_keys = AGENT_CONFIG_KEYS
            config = {k: kwargs.pop(k) for k in list(kwargs.keys()) if k in config_keys}
            # profile carries id + the remaining kwargs (name, age, persona, ...).
            profile = dict(kwargs)
            # Ensure id is present in profile (AgentBase.create expects profile["id"]).
            profile["id"] = agent_id_int

            specs.append(
                {
                    "id": agent_id_int,
                    "profile": profile,
                    "config": config,
                }
            )

        if not class_names:
            raise ValueError("No agent configs provided.")
        if len(class_names) > 1:
            raise ValueError(
                f"Streaming mode supports a single agent class per society; "
                f"got multiple: {sorted(class_names)}"
            )
        return specs, class_names.pop()

    def _update_pid_file(self, status: str, **kwargs):
        """更新 pid.json 文件"""
        # 读取现有数据以保留进度信息
        pid_data = {}
        if self.pid_file.exists():
            try:
                with open(self.pid_file, "r", encoding="utf-8") as f:
                    pid_data = json.load(f)
            except (OSError, json.JSONDecodeError):
                logger.debug(
                    "Failed to read existing pid file, starting fresh", exc_info=True
                )

        # 更新基本字段
        pid_data.update(
            {
                "pid": os.getpid(),
                "status": status,
                "start_time": pid_data.get("start_time", datetime.now(UTC).isoformat()),
                **kwargs,
            }
        )

        if status == "completed" or status == "failed":
            pid_data["end_time"] = datetime.now(UTC).isoformat()

        with open(self.pid_file, "w", encoding="utf-8") as f:
            json.dump(pid_data, f, indent=2, ensure_ascii=False)

    def _update_progress(self):
        """更新模拟进度到 pid.json"""
        if self.society:
            progress_data = {
                "simulation_time": self.society.current_time.isoformat(),
                "step_count": self.society.step_count,
            }
            self._update_pid_file("running", **progress_data)

    async def run(
        self,
        config_path: Path,
        steps_path: Path,
        experiment_id: str | None = None,
        replay_disable: bool = False,
        batch_size: int | None = None,
        resume: bool = False,
    ):
        """
        运行实验

        :param config_path: 配置文件路径（init_config.json）
        :param steps_path: steps.yaml 文件路径
        :param experiment_id: 实验ID（可选）
        :param replay_disable: 为 True 时构造一个禁用的 ``ReplayProxy`` （无 replay JSONL 写）。
        :param batch_size: 每个 ``step_agent_batch`` Ray Task 处理的 agent 数；
            ``None`` 时回落 ``Config.BATCH_SIZE`` （环境变量 ``AGENTSOCIETY_BATCH_SIZE`` ，缺省 256）。
        :param resume: 为 True 时从 ``run_dir/SOCIETY.json`` 恢复 env 模块状态与 society
            时钟/步数，跳过已完成的 ``RunStep`` （Ask/Intervene/Questionnaire 会重跑）。
        """
        try:
            # 验证环境变量（必须在任何操作之前）
            self._validate_environment()

            # 更新状态为运行中
            self._update_pid_file("running", experiment_id=experiment_id)

            # 加载配置
            logger.info(f"Loading config from {config_path}")
            config = self._load_config(config_path)

            # 提取配置信息（现在config是InitConfig模型）
            env_modules_config = config.env_modules
            agent_configs = config.agents
            env_module_types = [m.module_type for m in env_modules_config]
            env_kwargs = {m.module_type: m.kwargs for m in env_modules_config}

            # 转换agent配置为字典格式（用于_create_agents方法）
            agent_args = [
                {
                    "agent_id": agent.agent_id,
                    "agent_type": agent.agent_type,
                    "kwargs": agent.kwargs,
                }
                for agent in agent_configs
            ]

            # 加载步骤配置
            logger.info(f"Loading steps from {steps_path}")
            steps_config = self._load_steps(steps_path)

            start_t = datetime.fromisoformat(steps_config.start_t)
            steps = steps_config.steps

            # steps.yaml 的 hash：写入 SOCIETY.json，resume 时比对以检测漂移。
            steps_hash = hashlib.sha256(steps_path.read_bytes()).hexdigest()

            # ── Resume：从 run_dir/SOCIETY.json + SOCIETY_STEP.json 续跑。 ──────
            # resume 时以持久化的 env_module_types/env_kwargs/时钟/步数为准
            # （而非 config 文件，避免配置漂移污染续跑）。
            society_json = (
                self.run_dir / "SOCIETY.json" if self.run_dir is not None else None
            )
            resume_meta: dict | None = None
            completed_step_count = 0  # 已完成的前置顶层 step 数（含 Ask/Intervene）
            sim_step_cursor = 0  # 已完成的仿真 tick 数（用于 RunStep 部分跳过）
            if resume:
                if society_json is None or not society_json.exists():
                    raise SystemExit(
                        "--resume requested but no SOCIETY.json found in run_dir "
                        f"(looked for {society_json})"
                    )
                try:
                    resume_meta, step_meta = AgentSociety._read_checkpoint(self.run_dir)
                except (FileNotFoundError, ValueError) as exc:
                    raise SystemExit(f"--resume failed: {exc}") from exc
                env_module_types = list(resume_meta.get("env_module_types", []))
                env_kwargs = dict(resume_meta.get("env_kwargs", {}))
                if step_meta.get("current_time"):
                    start_t = datetime.fromisoformat(str(step_meta["current_time"]))
                sim_step_cursor = int(step_meta.get("step_count", 0))
                completed_step_count = int(step_meta.get("completed_step_count", 0))
                # steps.yaml 漂移检测：编辑过 steps 会让位置型游标错位。
                ckpt_hash = resume_meta.get("steps_hash")
                if ckpt_hash and ckpt_hash != steps_hash:
                    logger.warning(
                        "steps.yaml has changed since the checkpoint was written "
                        "(hash %s -> %s). Resume step-skip may be inaccurate; "
                        "verify the steps file matches the original run.",
                        str(ckpt_hash)[:12],
                        steps_hash[:12],
                    )
                logger.info(
                    "Resuming from %s: %d top-level step(s) done, %d sim tick(s) "
                    "(time=%s)",
                    society_json,
                    completed_step_count,
                    sim_step_cursor,
                    start_t.isoformat(),
                )
                self._update_pid_file(
                    "running",
                    resumed=True,
                    resumed_from_step=completed_step_count,
                )
            elif society_json is not None and society_json.exists():
                logger.warning(
                    "%s already exists (a prior run). Pass --resume to continue it; "
                    "running fresh will overwrite agent/env state.",
                    society_json,
                )

            # env workspace 按 module_type 建目录，重复类型会冲突，提前拒绝。
            if len(set(env_module_types)) != len(env_module_types):
                raise ValueError(
                    f"Duplicate env module types in config: {env_module_types}. "
                    "Each env module maps to run_dir/env/<module_type>/."
                )

            # 扫描并注册自定义模块（在创建环境模块之前）
            workspace_path = self.run_dir.resolve()
            # 向上查找包含 custom/ 目录的工作区根目录
            custom_root = workspace_path
            while custom_root.parent != custom_root:
                if (custom_root / "custom").is_dir():
                    break
                custom_root = custom_root.parent
            if (custom_root / "custom").is_dir():
                logger.info(f"Scanning custom modules from {custom_root}")
                scan_and_register_custom_modules(custom_root)
            else:
                logger.info("No custom/ directory found, skipping custom module scan")

            # Initialize Ray / per-process LLM dispatch support. ``init_dispatchers``
            # is idempotent.
            from agentsociety2.config.llm_dispatcher import (
                init_dispatchers,
            )

            await init_dispatchers()

            # ── Replay: distributed ReplayProxy (JSONL sink) ──────────────────────
            # Replay is distributed & lock-free: ReplayProxy carries only the
            # replay dir; env/society/agents each build their own local
            # ReplaySink and append sharded JSONL. ``--replay-disable`` yields a
            # disabled proxy (enabled=False) so writes are no-ops.
            from agentsociety2.storage.replay_proxy import ReplayProxy

            replay_proxy: ReplayProxy | None = None
            replay_enabled = not replay_disable
            if self.run_dir is not None:
                replay_dir = (self.run_dir / "replay").resolve()
                replay_proxy = ReplayProxy(
                    replay_dir=str(replay_dir), enabled=replay_enabled
                )
                logger.info(
                    "Replay proxy initialized (enabled=%s, dir=%s)",
                    replay_enabled,
                    replay_dir,
                )

            # Build injected LLM clients for the env actor. Each carries only
            # connection params; the actor builds its own Router + AIMD semaphore
            # in its own event loop on first call (no module-global pool).
            from agentsociety2.config.llm_dispatcher import build_client_for_role

            llm_clients_spec = {
                "coder": build_client_for_role("coder"),
                "default": build_client_for_role("default"),
            }
            # 并发度：所有 env 模块都声明 is_concurrency_safe() 才开并行 ask，否则串行。
            env_type_map = dict(get_registered_env_modules())
            all_safe = all(
                env_type_map[t].is_concurrency_safe()
                for t in env_module_types
                if t in env_type_map
            )
            max_concurrency = Config.ENV_ACTOR_MAX_CONCURRENCY if all_safe else 1

            # Trace wiring: distributed & lock-free now. TraceProxy just carries
            # the output dir; both the env router actor and the agents' own
            # ServiceProxy build local ShardedAppendSinks from it (otherwise
            # env-side codegen/summary LLM calls are untraced).
            from agentsociety2.trace import TraceProxy

            trace_proxy: TraceProxy | None = None
            if self.run_dir is not None:
                trace_base = (self.run_dir / "trace").resolve()
                trace_proxy = TraceProxy(trace_dir=str(trace_base))

            actor_cls = get_env_router_actor_class(max_concurrency=max_concurrency)
            env_actor = actor_cls.remote(
                env_module_types,
                env_kwargs,
                str(self.run_dir.resolve()) if self.run_dir is not None else None,
                {
                    "final_summary_enabled": config.codegen_router.final_summary_enabled,
                },
                llm_clients_spec,
                replay_proxy,
                trace_proxy,
            )
            env_router = EnvRouterProxy(
                env_actor,
                run_dir=self.run_dir.resolve(),
                env_module_types=env_module_types,
            )
            self._env_router = env_router

            # Compose the agent ServiceProxy with serializable LLM clients plus
            # the same trace proxy and replay proxy used by the env router.
            from agentsociety2.agent.service_proxy import build_service_proxy

            service_proxy = build_service_proxy(
                env_router,
                run_dir=self.run_dir,
                trace=trace_proxy if trace_proxy is not None else True,
                replay=replay_proxy,
            )

            if resume_meta is not None:
                logger.info(
                    "Resuming AgentSociety from %s (agent workspaces reused, "
                    "env modules restored by the actor)",
                    society_json,
                )
                # from_workspace 读 SOCIETY.json 还原 society；env 由 actor 恢复。
                self.society = await AgentSociety.from_workspace(
                    self.run_dir,
                    env_router=env_router,
                    service_proxy=service_proxy,
                )
            else:
                logger.info(f"Building {len(agent_args)} agent specs (record-based)...")
                agent_specs, agent_class_name = self._build_agent_specs(agent_args)
                logger.info(
                    "Creating AgentSociety instance (record-based, no agent objects)..."
                )
                self.society = AgentSociety(
                    agent_specs=agent_specs,
                    agent_class_name=agent_class_name,
                    env_router=env_router,
                    start_t=start_t,
                    run_dir=self.run_dir,
                    service_proxy=service_proxy,
                    batch_size=(
                        int(batch_size)
                        if batch_size is not None
                        else int(Config.BATCH_SIZE)
                    ),
                    enable_replay=not replay_disable,
                    env_module_types=env_module_types,
                    env_kwargs=env_kwargs,
                )
            # fresh 路径记录 steps_hash（resume 路径已由 from_workspace 从 checkpoint 还原）。
            self.society._steps_hash = steps_hash

            await self.society.init()
            logger.info("AgentSociety initialized")

            # 执行步骤
            logger.info(f"Executing {len(steps)} steps...")
            # resume 游标：
            # - completed_step_count：上一轮已完成的「顶层 step」数（含 Ask/Intervene/
            #   Questionnaire）。idx < 它的步骤整段跳过，避免重跑已执行的 Ask 产生
            #   错位的 artifact。
            # - sim_step_cursor：上一轮已完成的仿真 tick 数。仅 RunStep 推进，
            #   用于跳过部分完成的 RunStep。

            for step_idx, step in enumerate(steps):
                if self._should_terminate:
                    logger.info("Termination requested, stopping execution")
                    break

                # 记录「正在执行第 step_idx 个顶层 step」——崩溃时持久化的
                # completed_step_count 即此值，resume 据此跳过已执行的前置步。
                self.society._completed_step_count = step_idx

                # resume：整段跳过上一轮已完成的前置 step（任何类型）。
                if step_idx < completed_step_count:
                    if isinstance(step, RunStep):
                        sim_step_cursor = max(0, sim_step_cursor - step.num_steps)
                    logger.info(
                        "Skipping step %d (%s) — already completed before resume",
                        step_idx,
                        type(step).__name__,
                    )
                    continue

                step_type = step.type

                # 更新进度到 pid.json
                self._update_progress()

                try:
                    if isinstance(step, RunStep):
                        # resume：本 RunStep 可能已部分完成，用仿真 tick 游标算剩余。
                        remaining = step.num_steps - sim_step_cursor
                        sim_step_cursor = max(0, sim_step_cursor - step.num_steps)
                        if remaining <= 0:
                            logger.info(
                                "Skipping RunStep %d (%d steps already completed)",
                                step_idx,
                                step.num_steps,
                            )
                            continue

                        logger.info(
                            f"Running {remaining}/{step.num_steps} steps with tick={step.tick}"
                        )

                        # 创建定期更新进度的任务
                        async def update_progress_periodically():
                            while not self._should_terminate:
                                await asyncio.sleep(1)  # 每秒更新一次
                                if self.society and not self._should_terminate:
                                    self._update_progress()

                        progress_task = asyncio.create_task(
                            update_progress_periodically()
                        )
                        try:
                            await self.society.run(num_steps=remaining, tick=step.tick)
                        finally:
                            progress_task.cancel()
                            try:
                                await progress_task
                            except asyncio.CancelledError:
                                logger.debug(
                                    "Progress task cancelled after step completion"
                                )
                        # 最终更新进度
                        self._update_progress()

                    elif isinstance(step, AskStep):
                        logger.info(f"Asking: {step.question}")
                        answer = await self.society.ask(step.question)
                        logger.info(f"Answer: {answer}")

                        # 保存结果到artifacts目录，使用模拟时间作为文件命名，Markdown格式
                        sim_time = self.society.current_time
                        timestamp = sim_time.strftime("%Y%m%d_%H%M%S")
                        artifact_file = (
                            self.artifacts_dir / f"ask_step_{step_idx}_{timestamp}.md"
                        )
                        with open(artifact_file, "w", encoding="utf-8") as f:
                            # YAML front matter
                            f.write("---\n")
                            f.write(
                                f"question: {yaml.dump(step.question, allow_unicode=True, default_flow_style=False).rstrip()}\n"
                            )
                            f.write("---\n\n")
                            # Markdown content
                            f.write(f"{answer}\n")
                        logger.info(f"Ask result saved to {artifact_file}")

                    elif isinstance(step, InterveneStep):
                        logger.info(f"Intervening: {step.instruction}")
                        intervene_result = await self.society.intervene(
                            step.instruction
                        )
                        logger.info(f"Result: {intervene_result}")

                        # 保存结果到artifacts目录，使用模拟时间作为文件命名，Markdown格式
                        sim_time = self.society.current_time
                        timestamp = sim_time.strftime("%Y%m%d_%H%M%S")
                        artifact_file = (
                            self.artifacts_dir
                            / f"intervene_step_{step_idx}_{timestamp}.md"
                        )
                        with open(artifact_file, "w", encoding="utf-8") as f:
                            # YAML front matter
                            f.write("---\n")
                            f.write(
                                f"instruction: {yaml.dump(step.instruction, allow_unicode=True, default_flow_style=False).rstrip()}\n"
                            )
                            f.write("---\n\n")
                            # Markdown content
                            f.write(f"{intervene_result}\n")
                        logger.info(f"Intervene result saved to {artifact_file}")

                    elif isinstance(step, QuestionnaireStep):
                        questionnaire = Questionnaire(
                            questionnaire_id=step.questionnaire_id,
                            title=step.title or "",
                            description=step.description or "",
                            questions=step.questions,
                        )
                        logger.info(
                            "Running questionnaire %s with %s questions",
                            questionnaire.questionnaire_id,
                            len(questionnaire.questions),
                        )
                        questionnaire_result = await self.society.run_questionnaire(
                            questionnaire,
                            target_agent_ids=step.target_agent_ids,
                        )

                        sim_time = self.society.current_time
                        timestamp = sim_time.strftime("%Y%m%d_%H%M%S")
                        artifact_file = (
                            self.artifacts_dir
                            / f"questionnaire_step_{step_idx}_{timestamp}.json"
                        )
                        with open(artifact_file, "w", encoding="utf-8") as f:
                            json.dump(
                                questionnaire_result.model_dump(mode="json"),
                                f,
                                indent=2,
                                ensure_ascii=False,
                            )
                        logger.info(
                            "Questionnaire result saved to %s",
                            artifact_file,
                        )

                    else:
                        logger.warning(f"Unknown step type: {step_type}, skipping")
                        continue

                    # 更新进度到 pid.json（步骤完成）
                    self._update_progress()
                    # 标记该顶层 step 已完成并持久化——确保后续崩溃 resume 时
                    # 不会重跑已完成的 Ask/Intervene/Questionnaire。
                    self.society.mark_step_completed(step_idx)

                except Exception as e:
                    logger.error(
                        f"Error executing step {step_idx} ({step_type}): {e}",
                        exc_info=True,
                    )

                    # 已推进的状态可能只部分落盘，不能继续后续步骤或报告成功。
                    # 外层统一标记 failed、记录错误并关闭自有资源。
                    raise

            # 关闭society
            self._log_llm_stats()
            step_failure_count = getattr(self.society, "_step_failure_count", 0)
            await self.society.close()
            if step_failure_count:
                # Some top-level steps caught their errors and the loop ran to
                # the end, but agent steps failed inside — an unqualified
                # "completed" here is how broken runs went unnoticed before.
                logger.warning(
                    "Experiment completed with %d agent step failure(s) "
                    "(see core_step_failures in replay for details)",
                    step_failure_count,
                )
                self._update_pid_file(
                    "completed_with_errors", step_failures=step_failure_count
                )
            else:
                logger.info("Experiment completed successfully")
                self._update_pid_file("completed")

        except Exception as e:
            logger.error(f"Experiment failed: {e}", exc_info=True)
            self._log_llm_stats()
            self._update_pid_file("failed", error=str(e))
            # Ensure routing subprocesses are cleaned up on failure
            if self.society is not None:
                try:
                    await self.society.close()
                except Exception:
                    logger.debug(
                        "Error closing society during failure cleanup", exc_info=True
                    )
            raise

    def _log_llm_stats(self) -> None:
        """收尾汇报 LLM token 用量与 prompt 缓存命中率。

        在 ``close()`` **之前**调用：env router 的用量是快照，close 之后再取会丢。
        写 ``run_dir/LLM_STATS.json`` 并打一行汇总。统计失败绝不能影响实验结论，
        因此这里吞掉异常只记 debug。
        """
        if self.society is None:
            return
        try:
            payload = self.society.write_llm_stats_json()
        except Exception:
            logger.debug("Failed to write LLM stats", exc_info=True)
            return
        if payload is None:
            return
        totals = payload["totals"]
        logger.info(
            "LLM usage: calls=%d, input=%d (cached=%d, hit rate=%.1f%%), output=%d",
            totals["calls"],
            totals["input"],
            totals["cached_input"],
            payload["cache_hit_rate"] * 100.0,
            totals["output"],
        )
        for model, s in sorted(payload["models"].items()):
            rate = (s["cached_input"] / s["input"] * 100.0) if s["input"] else 0.0
            logger.info(
                "LLM usage [%s]: calls=%d, input=%d, cached=%d (%.1f%%), output=%d",
                model,
                s["calls"],
                s["input"],
                s["cached_input"],
                rate,
                s["output"],
            )
        logger.info("LLM stats written to %s", self.run_dir / "LLM_STATS.json")


def main():
    """命令行入口"""
    # 早期环境变量验证（在任何操作之前）
    _validate_env_early()

    parser = argparse.ArgumentParser(
        description="Run AgentSociety2 simulation experiment"
    )
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to configuration file (init_config.json)",
    )
    parser.add_argument(
        "--steps",
        type=str,
        required=True,
        help="Path to steps.yaml file",
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        help="Path to run/ directory (default: current directory)",
        default=".",
    )
    parser.add_argument(
        "--experiment-id",
        type=str,
        help="Experiment ID (optional)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Path to log file (optional). If not specified, logs go to stdout/stderr only.",
    )
    parser.add_argument(
        "--replay-disable",
        action="store_true",
        help="Disable replay writing (no-op ReplayProxy; useful at 1M-agent scale).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help=(
            "Number of agents per step_agent_batch Ray Task. Tasks per tick = "
            "ceil(N / batch_size); at most AGENTSOCIETY_LLM_RAY_MAX_WORKERS run "
            "concurrently, so aim for ceil(N/batch_size) >= workers to saturate "
            "them. Default: AGENTSOCIETY_BATCH_SIZE env var, or 256."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume an interrupted run from run_dir/SOCIETY.json. Env module "
            "state and the society clock/step-count are restored; every "
            "already-completed top-level step (Run/Ask/Intervene/"
            "Questionnaire, persisted per step via mark_step_completed) is "
            "skipped, and execution continues from the first incomplete step."
        ),
    )

    args = parser.parse_args()

    # 设置日志级别
    set_logger_level(args.log_level)

    # 设置日志文件
    if args.log_file:
        add_file_handler(args.log_file, level=args.log_level)

    config_path = Path(args.config).resolve()
    steps_path = Path(args.steps).resolve()
    run_dir = Path(args.run_dir).resolve()

    # 验证文件存在
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    if not steps_path.exists():
        print(f"Error: Steps file not found: {steps_path}", file=sys.stderr)
        sys.exit(1)

    # 运行实验
    runner = ExperimentRunner(run_dir=run_dir)
    try:
        asyncio.run(
            runner.run(
                config_path=config_path,
                steps_path=steps_path,
                experiment_id=args.experiment_id,
                replay_disable=args.replay_disable,
                batch_size=args.batch_size,
                resume=args.resume,
            )
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Failed to run experiment: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
