"""
推荐服务层
"""

import asyncio
import time
from dataclasses import dataclass

from agentsociety2.logger import get_logger

from .algorithms.core import RatingMatrix, RecommenderAlgorithm


@dataclass
class ServiceConfig:
    """
    推荐服务配置

    :param cache_ttl: 缓存过期时间 (秒),默认 300秒
    :param max_batch_size: 最大批量推荐大小,默认 100
    :param timeout: 请求超时时间 (秒),默认 10秒
    """

    cache_ttl: int = 300
    max_batch_size: int = 100
    timeout: float = 10.0


class RecommendationService:
    """
    推荐服务
    """

    def __init__(
        self, algorithm: RecommenderAlgorithm, config: ServiceConfig = ServiceConfig()
    ):
        """
        初始化推荐服务

        :param algorithm: 推荐算法实例
        :param config: 服务配置
        """
        self._algorithm = algorithm
        self._config = config

        # 缓存: cache_key -> (timestamp, result)
        self._cache: dict[str, tuple[float, list[tuple[int, float]]]] = {}

        # 锁保护模型访问
        self._lock = asyncio.Lock()

        get_logger().info(
            f"RecommendationService 初始化: "
            f"algorithm={algorithm.get_algorithm_name()}, "
            f"cache_ttl={config.cache_ttl}s"
        )

    async def fit(self, data: RatingMatrix) -> None:
        """
        训练模型 (异步包装)

        :param data: 评分矩阵
        """
        get_logger().info(f"开始训练模型: {data}")

        async with self._lock:
            # 在线程池中执行同步训练
            await asyncio.to_thread(self._algorithm.fit, data)

        # 训练后清空缓存
        self._cache.clear()

        get_logger().info("模型训练完成")

    async def predict(self, user_id: int, item_id: int) -> float:
        """
        预测评分 (异步包装)

        :param user_id: 用户ID
        :param item_id: 物品ID

        :returns: 预测评分 (1.0-5.0)
        """
        return await asyncio.to_thread(self._algorithm.predict, user_id, item_id)

    async def recommend(
        self,
        user_id: int,
        n: int = 20,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """
        生成推荐 (带缓存)

        :param user_id: 用户ID
        :param n: 推荐数量
        :param exclude_ids: 额外要排除的物品ID集合

        :returns: [(item_id, score), ...] 按 score 降序排列
        """
        # 检查缓存；key 必须包含完整的排除集合，否则同样大小的不同集合
        # 会命中错误缓存并推荐已排除物品。
        exclude_set = exclude_ids or set()
        exclude_token = ",".join(str(item) for item in sorted(exclude_set))
        cache_key = f"{user_id}:{n}:{exclude_token}"

        if cache_key in self._cache:
            timestamp, cached_result = self._cache[cache_key]
            if time.time() - timestamp < self._config.cache_ttl:
                get_logger().debug(f"缓存命中: user={user_id}")
                return cached_result

        # 调用算法生成推荐
        result = await asyncio.to_thread(
            self._algorithm.recommend, user_id, n, exclude_set
        )

        # 更新缓存
        self._cache[cache_key] = (time.time(), result)

        get_logger().debug(f"为用户 {user_id} 生成 {len(result)} 条推荐")

        return result

    async def batch_recommend(
        self,
        user_ids: list[int],
        n: int = 20,
        exclude_ids: dict[int, set[int]] | None = None,
    ) -> dict[int, list[tuple[int, float]]]:
        """
        批量生成推荐

        :param user_ids: 用户ID列表
        :param n: 每个用户的推荐数量
        :param exclude_ids: 每个用户要排除的物品ID字典

        :returns: {user_id: [(item_id, score), ...], ...}
        """
        exclude_dict = exclude_ids or {}

        # 并发执行推荐
        tasks = [
            self.recommend(user_id=uid, n=n, exclude_ids=exclude_dict.get(uid))
            for uid in user_ids
        ]

        results = await asyncio.gather(*tasks)

        return {
            user_id: result for user_id, result in zip(user_ids, results, strict=False)
        }

    async def save_model(self, path: str) -> None:
        """
        保存模型 (异步包装)

        :param path: 模型保存路径
        """
        async with self._lock:
            await asyncio.to_thread(self._algorithm.save, path)

        get_logger().info(f"模型已保存到 {path}")

    async def load_model(self, path: str) -> None:
        """
        加载模型 (异步包装)

        :param path: 模型文件路径
        """
        async with self._lock:
            await asyncio.to_thread(self._algorithm.load, path)

        # 加载后清空缓存
        self._cache.clear()

        get_logger().info(f"模型已从 {path} 加载")

    def get_algorithm_info(self) -> dict[str, any]:
        """
        获取算法信息

        :returns: 算法信息字典
        """
        return self._algorithm.get_algorithm_info()

    def clear_cache(self) -> None:
        """清空缓存"""
        self._cache.clear()
        get_logger().info("推荐缓存已清空")

    def get_cache_stats(self) -> dict[str, any]:
        """
        获取缓存统计

        :returns: 缓存统计信息
        """
        current_time = time.time()
        valid_entries = sum(
            1
            for timestamp, _ in self._cache.values()
            if current_time - timestamp < self._config.cache_ttl
        )

        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_entries,
            "cache_ttl": self._config.cache_ttl,
        }
