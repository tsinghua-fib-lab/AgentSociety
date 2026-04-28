"""
推荐系统评估指标模块 
"""

import numpy as np
from typing import List, Tuple
from dataclasses import dataclass

from sklearn.metrics import roc_auc_score


@dataclass
class RecommendationMetrics:
    """推荐系统评估指标"""

    # 准确性指标
    rmse: float = 0.0
    mae: float = 0.0

    # 排序指标
    ndcg: float = 0.0          # NDCG@K (默认K=10)
    auc: float = 0.0           # 全局AUC
    uauc: float = 0.0          # User-wise AUC

    # 用户交互指标
    view_rate: float = 0.0
    rating_rate: float = 0.0
    avg_rating: float = 0.0


class MetricsCalculator:
    """评估指标计算器"""

    def __init__(self):
        """初始化计算器"""
        pass

    def calculate_rmse_mae(
        self,
        predictions: List[float],
        ground_truth: List[float]
    ) -> Tuple[float, float]:
        """
        计算RMSE和MAE

        Args:
            predictions: 预测评分列表
            ground_truth: 真实评分列表

        Returns:
            (rmse, mae)
        """
        if not predictions or not ground_truth:
            return 0.0, 0.0

        predictions = np.array(predictions)
        ground_truth = np.array(ground_truth)

        # RMSE
        rmse = np.sqrt(np.mean((predictions - ground_truth) ** 2))

        # MAE
        mae = np.mean(np.abs(predictions - ground_truth))

        return float(rmse), float(mae)

    def calculate_ndcg(
        self,
        user_ids: List[int],
        predictions: List[float],
        labels: List[int],
        k: int = 10
    ) -> Tuple[float, int]:
        """
        计算User-wise NDCG@K

        Args:
            user_ids: 用户ID列表
            predictions: 预测评分列表
            labels: 真实标签列表（0或1）
            k: NDCG@K的K值，默认10

        Returns:
            (ndcg, computed_users): NDCG值和成功计算的用户数
        """
        if len(user_ids) == 0 or len(predictions) == 0 or len(labels) == 0:
            return 0.0, 0

        user_ids = np.array(user_ids)
        predictions = np.array(predictions)
        labels = np.array(labels)

        # 按用户分组
        unique_users, inverse, counts = np.unique(
            user_ids, return_inverse=True, return_counts=True
        )
        index = np.argsort(inverse)

        # 为每个用户计算DCG/IDCG
        ndcg_list = []
        computed_users = 0

        total_num = 0
        for k_idx, user_id in enumerate(unique_users):
            start_id = total_num
            end_id = total_num + counts[k_idx]
            user_indices = index[start_id:end_id]

            # 跳过只有1个交互的用户
            if counts[k_idx] == 1:
                total_num += counts[k_idx]
                continue

            user_preds = predictions[user_indices]
            user_labels = labels[user_indices]

            # 检查标签唯一性
            if len(np.unique(user_labels)) < 2:
                total_num += counts[k_idx]
                continue

            # 计算DCG
            pos_num = user_labels.sum()
            if pos_num == 0 or pos_num == len(user_labels):
                total_num += counts[k_idx]
                continue

            # 按预测分数降序排序
            ranked_id = np.argsort(-user_preds)
            ranked_label = user_labels[ranked_id]

            # DCG计算
            flag = 1.0 / np.log2(np.arange(len(ranked_label)) + 2.0)
            dcg = (ranked_label * flag).sum()

            # IDCG计算（理想情况）
            idcg = flag[:int(pos_num)].sum()

            if idcg > 0:
                ndcg = dcg / idcg
                ndcg_list.append(ndcg)
                computed_users += 1

            total_num += counts[k_idx]

        if computed_users > 0:
            return float(np.mean(ndcg_list)), computed_users
        else:
            return 0.0, 0

    def calculate_auc(
        self,
        predictions: List[float],
        labels: List[int]
    ) -> float:
        """
        计算全局AUC

        Args:
            predictions: 预测评分列表
            labels: 真实标签列表（0或1）

        Returns:
            全局AUC值
        """
        if len(predictions) == 0 or len(labels) == 0:
            return 0.0

        predictions = np.array(predictions)
        labels = np.array(labels)

        # 检查标签唯一性
        if len(np.unique(labels)) < 2:
            return 0.0

        auc = roc_auc_score(labels, predictions)
        return float(auc)

    def calculate_uauc(
        self,
        user_ids: List[int],
        predictions: List[float],
        labels: List[int]
    ) -> Tuple[float, int]:
        """
        计算User-wise AUC

        Args:
            user_ids: 用户ID列表
            predictions: 预测评分列表
            labels: 真实标签列表（0或1）

        Returns:
            (uauc, computed_users): UAUC值和成功计算的用户数
        """
        if len(user_ids) == 0 or len(predictions) == 0 or len(labels) == 0:
            return 0.0, 0

        user_ids = np.array(user_ids)
        predictions = np.array(predictions)
        labels = np.array(labels)

        # 按用户分组
        unique_users, inverse, counts = np.unique(
            user_ids, return_inverse=True, return_counts=True
        )
        index = np.argsort(inverse)

        # 为每个用户计算AUC
        user_aucs = []
        computed_users = 0

        total_num = 0
        for k, user_id in enumerate(unique_users):
            start_id = total_num
            end_id = total_num + counts[k]
            user_indices = index[start_id:end_id]

            # 跳过只有一个交互的用户
            if counts[k] == 1:
                total_num += counts[k]
                continue

            user_preds = predictions[user_indices]
            user_labels = labels[user_indices]

            # 检查标签唯一性
            if len(np.unique(user_labels)) < 2:
                total_num += counts[k]
                continue

            try:
                user_auc = roc_auc_score(user_labels, user_preds)
                user_aucs.append(user_auc)
                computed_users += 1
            except Exception:
                pass

            total_num += counts[k]

        if computed_users > 0:
            uauc = np.mean(user_aucs)
            return float(uauc), computed_users
        else:
            return 0.0, 0


__all__ = [
    "RecommendationMetrics",
    "MetricsCalculator"
]
