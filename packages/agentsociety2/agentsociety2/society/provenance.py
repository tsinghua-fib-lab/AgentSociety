"""运行 provenance 清单。

一次仿真是否可复现，取决于运行时的代码、配置、依赖与模型信息是否能被
重建。本模块在实验启动时写一份 ``run_manifest.json`` ，记录种子、配置与
steps 的内容哈希、代码版本、依赖锁哈希以及 LLM 配置（不含密钥）。resume
时不会覆盖原始清单，而是把漂移后的清单写到 ``run_manifest.resume.json`` 。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agentsociety2.storage.workspace_state import atomic_write_text

MANIFEST_SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    """计算文件内容的 SHA-256。

    :param path: 待哈希文件路径。
    :returns: 十六进制摘要。
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_repo_root(start: Path) -> Path | None:
    """向上查找包含 ``.git`` 的仓库根目录。

    :param start: 起始路径。
    :returns: 仓库根目录；不在 git 仓库内时返回 ``None`` 。
    """
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _run_git(repo: Path, *args: str) -> str | None:
    """执行只读 git 命令。

    :param repo: 仓库根目录。
    :param args: git 子命令与参数。
    :returns: 去掉首尾空白的标准输出；失败时返回 ``None`` 。
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def collect_git_provenance(start: Path) -> dict[str, Any]:
    """收集代码版本信息。

    :param start: 用于定位仓库的起始路径。
    :returns: ``commit`` / ``dirty`` / ``root`` 字段。
    """
    repo = _find_repo_root(start)
    if repo is None:
        return {"commit": None, "dirty": None, "root": None}
    status = _run_git(repo, "status", "--porcelain")
    return {
        "commit": _run_git(repo, "rev-parse", "HEAD"),
        "dirty": None if status is None else bool(status),
        "root": str(repo),
    }


def collect_llm_provenance() -> dict[str, Any]:
    """收集 LLM 配置（不含任何密钥）。

    :returns: 模型、接口类型与推理控制字段。
    """
    from agentsociety2.config import Config

    # Paths, userinfo, query strings and arbitrary extra-body values may contain credentials.
    try:
        endpoint = urlsplit(Config.LLM_API_BASE or "")
        host = endpoint.hostname if endpoint.scheme in {"http", "https"} else None
        if host and ":" in host:
            host = f"[{host}]"
        port = endpoint.port
        origin = f"{endpoint.scheme}://{host}" if host else None
        if origin and port is not None:
            origin += f":{port}"
    except ValueError:
        origin = None
    return {
        "model": Config.LLM_MODEL,
        "coder_model": Config.CODER_LLM_MODEL,
        "embedding_model": Config.EMBEDDING_MODEL,
        "api_base": origin,
        "api_type": getattr(Config, "LLM_API_TYPE", None),
        "coder_api_type": getattr(Config, "CODER_LLM_API_TYPE", None),
        "thinking": Config.LLM_THINKING,
        "reasoning_effort": Config.LLM_REASONING_EFFORT,
        "extra_body_configured": bool(Config.LLM_EXTRA_BODY),
    }


def collect_runtime_provenance(start: Path) -> dict[str, Any]:
    """收集解释器、平台、包版本与依赖锁指纹。

    :param start: 用于定位 agentsociety2 代码仓库的起始路径（通常是包文件）。
    :returns: 运行时 provenance 字段。
    """
    import agentsociety2

    repo = _find_repo_root(start)
    lock_hash = None
    lock_path = None
    if repo is not None:
        candidate = repo / "uv.lock"
        if candidate.is_file():
            lock_path = str(candidate)
            lock_hash = sha256_file(candidate)
    return {
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "agentsociety2_version": getattr(agentsociety2, "__version__", None),
        "git": collect_git_provenance(start),
        "dependency_lock": {"path": lock_path, "sha256": lock_hash},
        "PYTHONHASHSEED": os.getenv("PYTHONHASHSEED"),
    }


def apply_seed(seed: int) -> None:
    """把种子应用到 Python 与 numpy 的全局随机源。

    :param seed: 非负整数种子。
    """
    os.environ["AGENTSOCIETY_SEED"] = str(seed)
    _seed_generators(seed)


def _seed_generators(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy 为可选依赖
        return
    np.random.seed(seed % (2**32))


def apply_seed_from_env(*task_identity: object) -> int | None:
    """在 Ray task/actor 进程内按 ``AGENTSOCIETY_SEED`` 重新播种。

    :returns: 应用的种子；未配置或非法时返回 ``None`` 。
    """
    raw = os.getenv("AGENTSOCIETY_SEED", "").strip()
    if not raw:
        return None
    try:
        seed = int(raw)
    except ValueError:
        return None
    if task_identity:
        key = json.dumps([seed, *task_identity], separators=(",", ":")).encode()
        seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    _seed_generators(seed)
    return seed


def build_run_manifest(
    config_path: Path,
    steps_path: Path,
    *,
    seed: int | None,
    batch_size: int | None,
    replay_disabled: bool,
    experiment_id: str | None,
) -> dict[str, Any]:
    """构建一次运行的 provenance 清单。

    :param config_path: ``init_config.json`` 路径。
    :param steps_path: ``steps.yaml`` 路径。
    :param seed: 用户提供的随机种子。
    :param batch_size: 每批 agent 数。
    :param replay_disabled: 是否禁用 replay。
    :param experiment_id: 实验 ID。
    :returns: 可序列化的清单字典。
    """
    from agentsociety2.config import Config

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "experiment_id": experiment_id,
        "seed": seed,
        "seed_applied": seed is not None,
        "config": {
            "path": str(Path(config_path).resolve()),
            "sha256": sha256_file(config_path),
        },
        "steps": {
            "path": str(Path(steps_path).resolve()),
            "sha256": sha256_file(steps_path),
        },
        "runtime": collect_runtime_provenance(Path(__file__).resolve()),
        "workspace_git": collect_git_provenance(Path(config_path).resolve().parent),
        "llm": collect_llm_provenance(),
        "execution": {
            "batch_size": batch_size if batch_size is not None else Config.BATCH_SIZE,
            "replay_disabled": replay_disabled,
            "code_exec_backend": Config.CODE_EXEC_BACKEND,
            "code_exec_timeout": Config.CODE_EXEC_TIMEOUT,
            "code_exec_memory_mib": Config.CODE_EXEC_MEMORY_MIB,
        },
    }


def write_run_manifest(
    run_dir: Path, manifest: dict[str, Any], *, resume: bool
) -> Path:
    """写出运行清单，resume 时保留原始清单。

    :param run_dir: 运行目录。
    :param manifest: :func:`build_run_manifest` 的产物。
    :param resume: 是否为 resume 运行。
    :returns: 实际写出的清单路径。
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    primary = run_dir / "run_manifest.json"
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)

    if not resume or not primary.exists():
        atomic_write_text(primary, text)
        return primary

    previous = json.loads(primary.read_text(encoding="utf-8"))
    same_config = previous.get("config", {}).get("sha256") == manifest["config"]["sha256"]
    same_steps = previous.get("steps", {}).get("sha256") == manifest["steps"]["sha256"]
    changed_settings = [
        key for key in ("seed", "llm", "execution") if previous.get(key) != manifest.get(key)
    ]
    if same_config and same_steps and not changed_settings:
        return primary

    resumed = run_dir / "run_manifest.resume.json"
    manifest = dict(manifest)
    manifest["resume_of"] = {
        "config_sha256": previous.get("config", {}).get("sha256"),
        "steps_sha256": previous.get("steps", {}).get("sha256"),
        "same_config": same_config,
        "same_steps": same_steps,
        "changed_settings": changed_settings,
    }
    atomic_write_text(
        resumed, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return resumed
