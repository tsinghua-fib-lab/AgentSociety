import asyncio
import json
import logging
import os
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

# Disable telemetry before any imports
os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# load_dotenv(".env.openrouter")
load_dotenv()

from agentsociety2.agent import PersonAgent
from agentsociety2.contrib.env.event_space import EventSpace
from agentsociety2.contrib.env.mobility_space import MobilitySpace
from agentsociety2.contrib.env.simple_social_space import SimpleSocialSpace
from agentsociety2.contrib.env.social_media import SocialMediaSpace
from agentsociety2.env import CodeGenRouter
from agentsociety2.logger import get_logger, setup_logging
from agentsociety2.society import AgentSociety


def _setup_debugpy_if_enabled(logger) -> None:
    """可选启用 debugpy attach（默认关闭）。"""
    enabled = os.getenv("ENABLE_DEBUGGER", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return

    host = os.getenv("DEBUGPY_HOST", "localhost")
    port = int(os.getenv("DEBUGPY_PORT", "5678"))

    try:
        import debugpy

        debugpy.listen((host, port))
        logger.info("debugpy enabled, waiting for debugger attach at %s:%s", host, port)
        debugpy.wait_for_client()
        logger.info("debugger attached, continuing simulation startup")
    except Exception:
        logger.exception("failed to initialize debugpy")
        raise


def _calculate_gyration_radius(trajectories: list) -> float:
    """
    计算回旋半径（Radius of Gyration）

    回旋半径是从轨迹质心到各个位置点的平均距离的均方根。

    Args:
        trajectories: 轨迹列表，每个元素是 (x, y) 坐标对

    Returns:
        回旋半径（单位：米）
    """
    if len(trajectories) == 0:
        return 0.0

    trajectories = np.array(trajectories)
    # 计算轨迹的质心
    centroid = trajectories.mean(axis=0)

    # 计算每个点到质心的距离
    distances = np.linalg.norm(trajectories - centroid, axis=1)

    # 计算均方根距离（回旋半径）
    gyration_radius = np.sqrt(np.mean(distances**2))

    return float(gyration_radius)


async def main(
    logger,
    num_agents: int = 50,
    profile_start_idx: int = 0,
):
    """
    运行集成多个环境模块的 Benchmark

    实验设置：
    - 模拟起点：当日早上 00:00:00 (UTC)
    - 时间步长：15 分钟 = 900 秒
    - 总步数：97 步（覆盖 24+ 小时）

    环境模块：
    1. 移动模块（MobilitySpace）：管理 agent 的地理位置和轨迹
    2. 事件模块（EventSpace）：处理环境中的事件
    3. 社交媒体模块（SocialMediaSpace）：处理社交交互和媒体内容

    数据统计：
    - 轨迹数据：每个agent的移动轨迹（(x, y) 坐标列表）
    - 访问的AOI：每个agent访问过的AOI集合
    - 回旋半径：衡量agent活动范围的指标
    - 日均访问地点数：每个agent访问的唯一地点数
    """
    logger.info("\n" + "=" * 80)
    logger.info("【集成多模块 Benchmark】")
    logger.info("=" * 80)
    logger.info("实验设置：")
    logger.info("  - 起始时间: 当日早上 00:00:00 (UTC)")
    logger.info("  - 时间步长: 15 分钟 (900 秒)")
    logger.info("  - 总步数: 97 步")
    logger.info(f"  - Agent 数量: {num_agents}")
    logger.info("【环境模块】:")
    logger.info("  1. 移动模块 (MobilitySpace)")
    logger.info("  2. 事件模块 (EventSpace)")
    logger.info("  3. 社交媒体模块 (SocialMediaSpace)")
    logger.info("=" * 80)

    # 实验参数
    # 从早上 7 点开始模拟
    START_TIME = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    TIME_STEP_MINUTES = 15  # 15 分钟
    TIME_STEP_SECONDS = TIME_STEP_MINUTES * 60  # 900 秒
    TOTAL_STEPS = 97

    # 用于存储需要清理的环境
    _mobility_env = None
    event_space = None
    social_media_env = None
    env_router = None
    agents = []

    # ==================== 加载 Profiles ====================
    logger.info("\n【步骤1/4】加载 profiles.json...")

    profiles_path = Path(
        os.environ.get("DAILY_MOBILITY_PROFILES_PATH")
        or Path(__file__).with_name("profiles.json")
    ).expanduser()
    if (
        not os.environ.get("DAILY_MOBILITY_PROFILES_PATH")
        and not profiles_path.is_file()
    ):
        profiles_path = Path(__file__).resolve().parents[1] / "profiles.json"
    if not os.path.exists(profiles_path):
        logger.error(f"  ❌ profiles.json 文件不存在: {profiles_path}")
        return

    with open(profiles_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    logger.info(f"  ✓ 加载了 {len(profiles)} 个 agent profiles")

    # 限制 agent 数量
    if num_agents > len(profiles):
        logger.warning(
            f"  ⚠ 请求的 agent 数量 ({num_agents}) 超过 profiles 数量 ({len(profiles)})，使用全部 {len(profiles)} 个"
        )
        num_agents = len(profiles)

    profiles_to_use = profiles[profile_start_idx : profile_start_idx + num_agents]

    # 【关键修复】动态获取实际的 agent_ids，而不是硬编码 1-num_agents
    actual_agent_ids = [p["id"] for p in profiles_to_use]
    logger.info(f"  ✓ 实际 Agent IDs: {actual_agent_ids}")

    # ==================== 初始化环境 ====================
    logger.info("\n【步骤2/4】初始化环境...")

    # ==================== 创建 Agents ====================
    logger.info(f"\n【步骤3/4】创建 {num_agents} 个 Agents...")

    agent_args = []
    mobility_persons = []
    for profile in profiles_to_use:
        agent_id = profile["id"]

        # 创建 agent（使用 profile 中的详细信息）
        # 构建个人资料字符串
        profile_text = f"My name is Agent-{agent_id}, age {profile.get('age', 30)}, gender {profile.get('gender', 'Unknown')}, education {profile.get('education', 'Unknown')}, occupation {profile.get('occupation', 'Unknown')}, home at {profile['home']}, work at {profile['work']}"

        agent_args.append(
            {
                "id": agent_id,
                "profile": profile_text,
                "template_mode_enabled": True,
                "ask_intention_enabled": True,
            }
        )
        mobility_persons.append(
            {
                "id": agent_id,
                "position": {
                    "kind": "aoi",
                    "aoi_id": profile["home"],
                },
            }
        )

    # 创建 MobilitySpace 环境
    # 使用相对路径而不是硬编码的 /root 路径
    home_dir = os.path.join(os.path.expanduser("~"), "agentsociety_data")
    _map_path = os.path.join(home_dir, "beijing.pb")
    os.makedirs(home_dir, exist_ok=True)

    mobility_env = MobilitySpace(_map_path, home_dir, persons=mobility_persons)
    # person = await mobility_env.get_person(1)
    # print(person)
    # input("Press Enter to continue...")
    event_space = EventSpace()

    # 创建社交媒体环境
    logger.info("\n【初始化社交媒体模块】")
    social_media_data_dir = os.getenv(
        "SOCIAL_MEDIA_DATA_DIR",
        os.path.join(os.path.expanduser("~/.agentsociety"), "social_media_data"),
    )
    logger.info(f"  ✓ 社交媒体数据目录: {social_media_data_dir}")
    social_media_env = SocialMediaSpace(data_dir=social_media_data_dir)

    # 创建 CodeGenRouter
    env_router = CodeGenRouter(
        env_modules=[mobility_env, event_space, social_media_env],
    )

    # 保存 pyi 代码
    with open("tools_pyi.pyi", "w") as f:
        f.write(env_router._tools_pyi_dict[(False, None)])

    # 生成世界描述（使用缓存）
    world_description = await env_router.get_world_description()
    print("--------------------------------")
    print(world_description)
    print("--------------------------------")

    # 实际初始化agents
    agents = [PersonAgent(**args) for args in agent_args]

    society = AgentSociety(
        agent_specs=[
            {"id": a.id, "profile": a._profile, "config": a._config} for a in agents
        ],
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=START_TIME,
    )
    await society.init()

    await society.run(num_steps=TOTAL_STEPS, tick=TIME_STEP_SECONDS)

    # ==================== 提取移动相关数据 ====================
    logger.info("\n【步骤5/5】提取移动统计数据...")

    # 从 MobilitySpace 环境中获取移动相关数据
    trajectories_dict = mobility_env.get_all_persons_trajectories()
    visited_aois_dict = mobility_env.get_all_persons_visited_aois()

    # 计算各项指标
    gyration_radius_list = []
    daily_location_numbers_list = []
    trajectory_lengths = []

    for agent_id in actual_agent_ids:
        # 获取该agent的轨迹
        trajectory = trajectories_dict.get(agent_id, [])
        visited_aois = visited_aois_dict.get(agent_id, set())

        # 计算回旋半径
        gr = _calculate_gyration_radius(trajectory)
        gyration_radius_list.append(gr)

        # 计算访问的唯一AOI数量
        dln = len(visited_aois)
        daily_location_numbers_list.append(dln)

        # 记录轨迹长度
        trajectory_lengths.append(len(trajectory))

        logger.info(f"  Agent {agent_id}:")
        logger.info(f"    - 轨迹点数: {len(trajectory)}")
        logger.info(f"    - 访问AOI数: {dln}")
        logger.info(f"    - 回旋半径: {gr:.2f} 米")
        if len(visited_aois) > 0:
            logger.info(
                f"    - 访问的AOI ID: {sorted(visited_aois)[:5]}{'...' if len(visited_aois) > 5 else ''}"
            )

    # 转换为 numpy 数组
    results = {
        "gyration_radius": np.array(gyration_radius_list, dtype=np.float64),
        "daily_location_numbers": np.array(daily_location_numbers_list, dtype=np.int32),
        "trajectories": trajectories_dict,  # 保留原始轨迹数据
        "visited_aois": visited_aois_dict,  # 保留访问的AOI数据
    }

    logger.info("\n  ✓ 数据提取完成")
    logger.info(f"    - gyration_radius shape: {results['gyration_radius'].shape}")
    logger.info(
        f"    - gyration_radius mean: {results['gyration_radius'].mean():.2f} 米"
    )
    logger.info(f"    - gyration_radius std: {results['gyration_radius'].std():.2f} 米")
    logger.info(
        f"    - daily_location_numbers shape: {results['daily_location_numbers'].shape}"
    )
    logger.info(
        f"    - daily_location_numbers mean: {results['daily_location_numbers'].mean():.2f}"
    )
    logger.info(
        f"    - daily_location_numbers max: {results['daily_location_numbers'].max()}"
    )

    # ==================== 保存结果 ====================
    logger.info("\n【保存结果】")

    output_dir = "benchmark_results"
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = os.path.join(output_dir, f"daily_mobility_results_{timestamp}.pkl")

    # 准备保存的数据
    save_data = {
        "results": {
            "gyration_radius": results["gyration_radius"],
            "daily_location_numbers": results["daily_location_numbers"],
        },
        "trajectories": results["trajectories"],
        "visited_aois": results["visited_aois"],
        "metadata": {
            "num_agents": num_agents,
            "actual_agent_ids": actual_agent_ids,
            "total_steps": TOTAL_STEPS,
            "time_step_minutes": TIME_STEP_MINUTES,
            "start_time": START_TIME.isoformat(),
            "timestamp": timestamp,
        },
    }

    with open(result_file, "wb") as f:
        pickle.dump(save_data, f)

    logger.info(f"  ✓ 结果已保存到: {result_file}")

    # 同时保存为JSON格式以便查看
    json_file = os.path.join(output_dir, f"daily_mobility_results_{timestamp}.json")
    json_data = {
        "results": {
            "gyration_radius": results["gyration_radius"].tolist(),
            "daily_location_numbers": results["daily_location_numbers"].tolist(),
        },
        "metadata": save_data["metadata"],
    }
    with open(json_file, "w") as f:
        json.dump(json_data, f, indent=2)

    logger.info(f"  ✓ JSON格式结果已保存到: {json_file}")

    await society.close()


async def main_social(
    logger,
    num_agents: int = 1,
    profile_start_idx: int = 0,
):
    """
    运行 DailyMobility Benchmark

    实验设置：
    - 模拟起点：当日早上 00:00:00 (UTC)
    - 时间步长：15 分钟 = 900 秒
    - 总步数：97 步（覆盖 24+ 小时）
    """
    logger.info("\n" + "=" * 80)
    logger.info("【DailyMobility Benchmark】")
    logger.info("=" * 80)
    logger.info("实验设置：")
    logger.info("  - 起始时间: 当日早上 00:00:00 (UTC)")
    logger.info("  - 时间步长: 15 分钟 (900 秒)")
    logger.info("  - 总步数: 97 步 (覆盖 7:00 - 23:15)")
    logger.info(f"  - Agent 数量: {num_agents}")
    logger.info("=" * 80)

    # 实验参数
    # 从早上 7 点开始模拟
    START_TIME = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
    TIME_STEP_MINUTES = 15  # 15 分钟
    TIME_STEP_SECONDS = TIME_STEP_MINUTES * 60  # 900 秒
    TOTAL_STEPS = 97

    # 用于存储需要清理的环境
    _mobility_env = None
    env_router = None
    agents = []

    # ==================== 加载 Profiles ====================
    logger.info("\n【步骤1/4】加载 profiles.json...")

    profiles_path = Path(
        os.environ.get("DAILY_MOBILITY_PROFILES_PATH")
        or Path(__file__).with_name("profiles.json")
    ).expanduser()
    if (
        not os.environ.get("DAILY_MOBILITY_PROFILES_PATH")
        and not profiles_path.is_file()
    ):
        profiles_path = Path(__file__).resolve().parents[1] / "profiles.json"
    if not os.path.exists(profiles_path):
        logger.error(f"  ❌ profiles.json 文件不存在: {profiles_path}")
        return

    with open(profiles_path, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    logger.info(f"  ✓ 加载了 {len(profiles)} 个 agent profiles")

    # 限制 agent 数量
    if num_agents > len(profiles):
        logger.warning(
            f"  ⚠ 请求的 agent 数量 ({num_agents}) 超过 profiles 数量 ({len(profiles)})，使用全部 {len(profiles)} 个"
        )
        num_agents = len(profiles)

    profiles_to_use = profiles[profile_start_idx : profile_start_idx + num_agents]

    # 【关键修复】动态获取实际的 agent_ids，而不是硬编码 1-num_agents
    actual_agent_ids = [p["id"] for p in profiles_to_use]
    logger.info(f"  ✓ 实际 Agent IDs: {actual_agent_ids}")

    # ==================== 初始化环境 ====================
    logger.info("\n【步骤2/4】初始化环境...")

    # ==================== 创建 Agents ====================
    logger.info(f"\n【步骤3/4】创建 {num_agents} 个 Agents...")

    agent_args = []
    mobility_persons = []
    for profile in profiles_to_use:
        agent_id = profile["id"]

        # 创建 agent（使用 profile 中的详细信息）
        # 构建个人资料字符串
        profile_text = f"My name is Agent-{agent_id}, age {profile.get('age', 30)}, gender {profile.get('gender', 'Unknown')}, education {profile.get('education', 'Unknown')}, occupation {profile.get('occupation', 'Unknown')}, home at {profile['home']}, work at {profile['work']}"

        agent_args.append(
            {
                "id": agent_id,
                "profile": profile_text,
            }
        )
        mobility_persons.append(
            {
                "id": agent_id,
                "position": {
                    "kind": "aoi",
                    "aoi_id": profile["home"],
                },
            }
        )

    # 创建 MobilitySpace 环境
    # 使用相对路径而不是硬编码的 /root 路径
    home_dir = os.path.join(os.path.expanduser("~"), "agentsociety_data")
    _map_path = os.path.join(home_dir, "beijing.pb")
    os.makedirs(home_dir, exist_ok=True)

    social_env = SimpleSocialSpace(
        agent_id_name_pairs=[
            (agent_id, profile.get("name", f"Agent-{agent_id}"))
            for agent_id, profile in zip(actual_agent_ids, profiles_to_use)
        ]
    )
    # # 创建 DailySpace 环境（使用实际的 agent_ids）
    # daily_env = DailySpace(person_ids=actual_agent_ids)

    # 创建 CodeGenRouter
    env_router = CodeGenRouter(env_modules=[social_env])

    # 生成世界描述（使用缓存）
    world_description = await env_router.get_world_description()
    print("--------------------------------")
    print(world_description)
    print("--------------------------------")

    # 实际初始化agents
    agents = [PersonAgent(**args) for args in agent_args]

    society = AgentSociety(
        agent_specs=[
            {"id": a.id, "profile": a._profile, "config": a._config} for a in agents
        ],
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=START_TIME,
    )
    await society.init()

    await society.run(num_steps=TOTAL_STEPS, tick=TIME_STEP_SECONDS)

    await society.close()


if __name__ == "__main__":
    setup_logging(
        log_file=f"logs/daily_mobility_benchmark-{datetime.now().strftime('%Y%m%d%H%M%S')}.log",
        log_level=logging.DEBUG,
    )
    logger = get_logger()
    _setup_debugpy_if_enabled(logger)
    asyncio.run(main(logger=logger, num_agents=50))
