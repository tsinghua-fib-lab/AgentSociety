import math
import random
from datetime import datetime

from .models import Post


def _get_pretrained_algorithm(algorithm_name: str, model_path: str | None):
    """
    根据算法名和模型路径加载预训练推荐模型。
    预训练方式：使用 recommendation 子模块训练后 save(path)，此处 load(path) 即可接入。

    :param algorithm_name: 如 "mf", "ncf", "lightgcn" 等，需与 recommendation.algorithms 中实现一致。
    :param model_path: 预训练模型文件路径（如 .pkl 或 目录）。

    :returns: 已 load 的 RecommenderAlgorithm 实例，若 model_path 为空则返回 None。
    """
    if not model_path:
        return None
    algo = None
    if algorithm_name == "mf":
        from .recommendation.algorithms.mf import MFConfig, MFRecommender

        algo = MFRecommender(config=MFConfig())
    # 可在此扩展: "ncf" -> NCFRecommender, "lightgcn" -> LightGCNRecommender 等
    if algo is None:
        return None
    try:
        algo.load(model_path)
    except Exception:
        return None
    return algo


class RecommendationEngine:
    """
    推荐算法引擎。支持规则算法（时间序、热度、Twitter 排序、随机）与预训练模型（如 MF）。
    预训练模型：在 recommendation 子模块中训练并 save(path)，构造时传入 model_path 与 algorithm 即可接入。
    """

    def __init__(
        self,
        model_path: str | None = None,
        recommendation_algorithm: str = "mf",
    ):
        """
        :param model_path: 预训练模型路径。非空时加载对应算法并可在 refresh_feed 中通过 algorithm="mf" 使用。
        :param recommendation_algorithm: 算法名，如 "mf"。需与 recommendation.algorithms 中实现一致。
        """
        self._model_algorithm = _get_pretrained_algorithm(
            recommendation_algorithm, model_path
        )
        self._model_algorithm_name = (
            recommendation_algorithm if self._model_algorithm else None
        )

    def get_model_algorithm_name(self) -> str | None:
        """若已加载预训练模型，返回算法名（如 'mf'），否则返回 None。"""
        return self._model_algorithm_name

    def model_recommend(
        self,
        posts: list[Post],
        user_id: int,
        limit: int = 20,
        exclude_post_ids: set[int] | None = None,
    ) -> list[Post]:
        """
        使用预训练模型对候选帖子排序。未加载模型时回退为时间序。

        :param posts: 候选帖子列表（item_id = post_id）
        :param user_id: 用户 ID
        :param limit: 返回条数
        :param exclude_post_ids: 需要排除的 post_id 集合（如已读）

        :returns: 按模型打分排序的帖子列表
        """
        if not posts:
            return []
        exclude = set(exclude_post_ids or [])
        post_by_id = {p.post_id: p for p in posts}
        candidate_ids = [p.post_id for p in posts]

        if self._model_algorithm is None:
            return self.chronological(posts, user_id, limit)

        try:
            rec_list = self._model_algorithm.recommend(user_id, limit, exclude)
        except Exception:
            return self.chronological(posts, user_id, limit)

        out: list[Post] = []
        added_ids: set[int] = set()
        for item_id, _score in rec_list:
            if (
                item_id in post_by_id
                and item_id not in exclude
                and item_id not in added_ids
            ):
                out.append(post_by_id[item_id])
                added_ids.add(item_id)
            if len(out) >= limit:
                break
        # 若模型返回不足或含大量未在候选中的 id，用候选集顺序补足
        for pid in candidate_ids:
            if len(out) >= limit:
                break
            if pid not in added_ids:
                out.append(post_by_id[pid])
                added_ids.add(pid)
        return out[:limit]

    @staticmethod
    def chronological(posts: list[Post], user_id: int, limit: int = 20) -> list[Post]:
        """
        时间序列排序算法（基线）

        :param posts: 所有候选帖子列表
        :param user_id: 当前用户ID
        :param limit: 返回帖子数量

        :returns: 按时间倒序排列的帖子列表
        """
        # 按创建时间降序排序
        sorted_posts = sorted(posts, key=lambda p: p.created_at, reverse=True)
        return sorted_posts[:limit]

    @staticmethod
    def reddit_hot(posts: list[Post], user_id: int, limit: int = 20) -> list[Post]:
        """
        Reddit热度算法

        基于点赞数和时间衰减计算热度分数。
        公式: score = sign * log10(|likes|) + (created_at_seconds - epoch) / 45000

        参考: https://medium.com/hacking-and-gonzo/how-reddit-ranking-algorithms-work-ef111e33d0d9

        :param posts: 所有候选帖子列表
        :param user_id: 当前用户ID
        :param limit: 返回帖子数量

        :returns: 按热度分数排序的帖子列表
        """

        def calculate_hot_score(post: Post) -> float:
            """
            计算帖子的Reddit热度分数

            注意：这里简化了公式，只考虑点赞数
            """
            # 点赞数（没有dislike，所以s = num_likes）
            s = post.likes_count

            # log10(|s|) with minimum of 1 to avoid log(0)
            order = math.log10(max(abs(s), 1))

            sign = 1 if s > 0 else 0 if s == 0 else -1

            # 时间部分
            epoch = datetime(1970, 1, 1)
            td = post.created_at - epoch
            epoch_seconds = td.days * 86400 + td.seconds + (td.microseconds / 1e6)

            # Reddit epoch offset (2005-12-08)
            reddit_epoch = 1134028003
            seconds = epoch_seconds - reddit_epoch

            # 最终分数
            score = sign * order + seconds / 45000

            return round(score, 7)

        # 计算所有帖子的热度分数
        post_scores = [(post, calculate_hot_score(post)) for post in posts]

        # 按热度分数降序排序
        post_scores.sort(key=lambda x: x[1], reverse=True)

        # 返回top N
        return [post for post, score in post_scores[:limit]]

    @staticmethod
    def twitter_ranking(
        posts: list[Post],
        user_id: int,
        limit: int = 20,
        follows: dict[int, list[int]] | None = None,
        weights: dict[str, float] | None = None,
    ) -> list[Post]:
        """
        Twitter排序算法

        综合多个因素的加权排序：
        - 是否关注作者（following_weight）
        - 互动数（likes + reposts + comments）（engagement_weight）
        - 新鲜度（时间）（recency_weight）
        - 互动率（engagement / views）（engagement_rate_weight）

        :param posts: 所有候选帖子列表
        :param user_id: 当前用户ID
        :param limit: 返回帖子数量
        :param follows: 关注关系 {follower_id: [followee_ids]}
        :param weights: 权重配置

        :returns: 按综合分数排序的帖子列表
        """
        # 默认权重
        default_weights = {
            "following": 0.4,  # 关注权重
            "engagement": 0.3,  # 互动数权重
            "recency": 0.2,  # 新鲜度权重
            "engagement_rate": 0.1,  # 互动率权重
        }

        if weights:
            default_weights.update(weights)

        follows = follows or {}

        # 用户关注的人
        following_ids = follows.get(user_id, [])

        # 当前时间
        max_time = max((p.created_at for p in posts), default=datetime.now())

        def calculate_twitter_score(post: Post) -> float:
            """计算Twitter排序分数"""
            score = 0.0

            # 1. 关注因素
            if post.author_id in following_ids:
                score += default_weights["following"]

            # 2. 互动数因素（归一化到0-1）
            total_engagement = (
                post.likes_count + post.reposts_count + post.comments_count
            )
            # 假设最大互动数为100
            engagement_normalized = min(total_engagement / 100.0, 1.0)
            score += default_weights["engagement"] * engagement_normalized

            # 3. 新鲜度因素（时间差越小，分数越高）
            time_diff_hours = (max_time - post.created_at).total_seconds() / 3600
            # 假设24小时内的帖子有新鲜度加成
            recency_score = max(0, 1 - time_diff_hours / 24.0)
            score += default_weights["recency"] * recency_score

            # 4. 互动率因素
            if post.view_count > 0:
                engagement_rate = total_engagement / post.view_count
                engagement_rate_normalized = min(engagement_rate, 1.0)
                score += default_weights["engagement_rate"] * engagement_rate_normalized

            return score

        # 计算所有帖子的分数
        post_scores = [(post, calculate_twitter_score(post)) for post in posts]

        # 按分数降序排序
        post_scores.sort(key=lambda x: x[1], reverse=True)

        # 返回top N
        return [post for post, score in post_scores[:limit]]

    @staticmethod
    def random_recommend(
        posts: list[Post], user_id: int, limit: int = 20
    ) -> list[Post]:
        """
        随机推荐算法（基线/对照组）

        :param posts: 所有候选帖子列表
        :param user_id: 当前用户ID
        :param limit: 返回帖子数量

        :returns: 随机选择的帖子列表
        """
        if len(posts) <= limit:
            return list(posts)
        else:
            return random.sample(posts, limit)


__all__ = ["RecommendationEngine"]
