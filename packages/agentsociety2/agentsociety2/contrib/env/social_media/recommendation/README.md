# 推荐系统模块

AgentSociety2 推荐系统模块提供了基于协同过滤的推荐算法实现,支持实时增量更新和灵活的服务组合。该模块采用简化的分层架构,将算法实现、推荐服务和训练逻辑清晰分离,易于扩展和维护。

## 目录

- [概述](#概述)
- [架构设计](#架构设计)
- [快速开始](#快速开始)
- [核心组件](#核心组件)
- [API 说明](#api-说明)
- [数据模型](#数据模型)
- [配置参数](#配置参数)
- [使用场景](#使用场景)
- [使用说明](#使用说明)

## 概述

推荐系统模块支持以下特性:

- **多算法支持**: 当前实现 MF (矩阵分解),架构支持扩展其他算法
- **可选增量训练**: 通过 `IncrementalTrainer` 支持实时数据更新
- **异步非阻塞**: 后台训练不影响推荐服务
- **并发安全**: 使用 `asyncio.Lock` 保证模型访问安全
- **模型持久化**: 支持模型保存和加载
- **冷启动处理**: 新用户/新物品的推荐策略
- **灵活组合**: 服务层和训练层可独立使用

## 架构设计

### 核心类

#### `RecommenderAlgorithm`

推荐算法的统一抽象基类,所有算法必须实现:

- `fit(data: RatingMatrix)`: 训练模型
- `predict(user_id: int, item_id: int)`: 预测评分
- `recommend(user_id: int, n: int, exclude_ids: Set[int])`: 生成推荐
- `save(path: str)`: 保存模型 (可选)
- `load(path: str)`: 加载模型 (可选)

#### `RatingMatrix`

评分数据的统一表示,支持多种格式转换:

- `from_ratings(ratings: List[Rating])`: 从评分列表构建
- `to_dataframe()`: 转换为 pandas DataFrame
- `to_sparse()`: 转换为稀疏矩阵
- `to_numpy()`: 转换为 NumPy 数组

#### `RecommendationService`

核心推荐服务层,负责:

- 异步转换 (算法是同步的)
- 推荐结果缓存
- 批量推荐支持
- 模型访问控制

#### `IncrementalTrainer`

可选的增量训练组件,负责:

- 监听新数据
- 触发条件检查
- 后台异步训练
- 训练任务管理

### 架构层次

![Draw by Gemini](https://webp-pic.yokumi.cn/2025/11/20251126212950223.png)

## 快速开始

### 场景 1: 简单推荐 (无增量更新)

```python
from agentsociety2.contrib.env.social_media.recommendation import (
    MFRecommender,
    MFConfig,
    RecommendationService,
    RatingMatrix,
    Rating,
)

# 1. 创建算法
config = MFConfig(n_latent_factors=50, n_iterations=100)
algorithm = MFRecommender(config)

# 2. 创建服务
service = RecommendationService(algorithm)

# 3. 准备数据并训练
ratings = [
    Rating(user_id=1, item_id=1, rating=5.0),
    Rating(user_id=1, item_id=2, rating=4.0),
    # ...
]
data = RatingMatrix.from_ratings(ratings)
await service.fit(data)

# 4. 生成推荐
recommendations = await service.recommend(user_id=1, n=10)
# 返回: [(item_id, score), ...]
```

### 场景 2: 增量更新

```python
from agentsociety2.contrib.env.social_media.recommendation import (
    MFRecommender,
    MFConfig,
    RecommendationService,
    IncrementalTrainer,
    TrainerConfig,
)

# 1. 创建算法和服务
algorithm = MFRecommender(MFConfig())
service = RecommendationService(algorithm)

# 2. 创建训练器
trainer_config = TrainerConfig(
    retrain_threshold_ratings=100,  # 新评分数阈值
    retrain_threshold_time=300,  # 时间阈值(秒)
    enable_auto_retrain=True,  # 启用自动重训练
)
trainer = IncrementalTrainer(service, trainer_config)

# 3. 加载初始数据
await trainer.load_initial_data(initial_ratings)

# 4. 添加新评分 (自动触发重训练)
await trainer.add_ratings(new_ratings)

# 5. 获取推荐
recommendations = await service.recommend(user_id=1, n=10)
```

### 运行完整示例

```bash
cd packages/agentsociety2
python example_new_architecture.py
```

示例包含:
1. 简单使用场景 (只需推荐)
2. 增量更新场景 (实时更新)
3. 批量推荐
4. 模型持久化

## 核心组件

### 1. 算法层 (`algorithms/`)

#### MFRecommender

矩阵分解推荐算法,基于 PyTorch 实现。

**特性**:
- 用户和物品的嵌入向量学习
- SGD 优化 + L2 正则化
- 冷启动处理 (基于热门度)
- 模型持久化支持

**文件结构**:
```
algorithms/
├── core.py           # RecommenderAlgorithm + RatingMatrix
└── mf/
    ├── config.py     # MFConfig 配置类
    ├── model.py      # MFRecommender 实现
    └── __init__.py
```

### 2. 服务层 (`service.py`)

#### RecommendationService

推荐服务的核心实现。

**关键方法**:
- `fit(data: RatingMatrix)`: 训练模型 (异步)
- `predict(user_id: int, item_id: int)`: 预测评分 (异步)
- `recommend(user_id, n, exclude_rated, exclude_ids)`: 生成推荐 (带缓存)
- `batch_recommend(user_ids, n)`: 批量推荐 (并发)
- `save_model(path)` / `load_model(path)`: 模型持久化

**功能特性**:
- **异步转换**: 使用 `asyncio.to_thread()` 包装同步算法
- **缓存管理**: TTL 缓存,自动过期清理
- **并发控制**: `asyncio.Lock` 保护模型访问
- **批量优化**: 并发执行多用户推荐

### 3. 训练层 (`trainer.py`)

#### IncrementalTrainer

可选的增量训练组件。

**关键方法**:
- `load_initial_data(ratings)`: 加载初始数据并训练
- `add_ratings(new_ratings)`: 添加新评分,检查触发条件
- `trigger_retrain()`: 手动触发重训练
- `get_trainer_info()`: 获取训练器状态

**触发机制**:
1. 评分数量阈值: `pending_ratings >= retrain_threshold_ratings`
2. 时间阈值: `time_since_last_train >= retrain_threshold_time`
3. 手动触发: 调用 `trigger_retrain()`

**训练流程**:
1. 拍摄所有评分的快照
2. 在后台异步训练新模型
3. 训练期间旧模型继续服务
4. 训练完成后原子替换模型

### 4. 数据模型 (`models.py`)

定义推荐系统的数据结构:

- `Item`: 物品信息
- `Rating`: 用户评分
- `UserPreference`: 用户偏好
- `FeedCache`: Feed 缓存
- `RecommendationHistory`: 推荐历史

## API 说明

### RecommendationService API

#### `fit(data: RatingMatrix) -> None`

训练推荐模型。

**参数**:
- `data`: 评分矩阵数据

**示例**:
```python
data = RatingMatrix.from_ratings(ratings)
await service.fit(data)
```

---

#### `predict(user_id: int, item_id: int) -> float`

预测用户对物品的评分。

**参数**:
- `user_id`: 用户 ID
- `item_id`: 物品 ID

**返回**: 预测评分 (1.0-5.0)

**示例**:
```python
score = await service.predict(user_id=1, item_id=100)
# 返回: 4.2
```

---

#### `recommend(user_id: int, n: int = 20, exclude_rated: bool = True, exclude_ids: Optional[Set[int]] = None) -> List[Tuple[int, float]]`

为用户生成推荐列表。

**参数**:
- `user_id`: 用户 ID
- `n`: 推荐数量
- `exclude_rated`: 是否排除已评分物品 (当前版本暂未实现,保留接口)
- `exclude_ids`: 额外要排除的物品 ID 集合

**返回**: `[(item_id, score), ...]` 按 score 降序排列

**示例**:
```python
recs = await service.recommend(user_id=1, n=10)
# 返回: [(101, 4.8), (203, 4.5), ...]
```

---

#### `batch_recommend(user_ids: List[int], n: int = 20, exclude_ids: Optional[Dict[int, Set[int]]] = None) -> Dict[int, List[Tuple[int, float]]]`

批量生成多个用户的推荐。

**参数**:
- `user_ids`: 用户 ID 列表
- `n`: 每个用户的推荐数量
- `exclude_ids`: 每个用户要排除的物品 ID 字典

**返回**: `{user_id: [(item_id, score), ...], ...}`

**示例**:
```python
results = await service.batch_recommend([1, 2, 3], n=5)
# 返回: {1: [(101, 4.8), ...], 2: [(205, 4.3), ...], ...}
```

---

#### `save_model(path: str) -> None`

保存模型到文件。

**参数**:
- `path`: 保存路径

**示例**:
```python
await service.save_model("model.pkl")
```

---

#### `load_model(path: str) -> None`

从文件加载模型。

**参数**:
- `path`: 模型文件路径

**示例**:
```python
await service.load_model("model.pkl")
```

---

#### `get_algorithm_info() -> Dict[str, Any]`

获取算法信息。

**返回**:
```python
{
    "name": str,  # 算法名称
    "config": dict,  # 算法配置
    "is_trained": bool,  # 是否已训练
    "num_users": int,  # 用户数量
    "num_items": int,  # 物品数量
}
```

---

#### `clear_cache() -> None`

清空推荐缓存。

---

#### `get_cache_stats() -> Dict[str, Any]`

获取缓存统计信息。

**返回**:
```python
{
    "total_entries": int,  # 缓存总条目数
    "valid_entries": int,  # 有效条目数
    "cache_ttl": int,  # 缓存过期时间(秒)
}
```

### IncrementalTrainer API

#### `load_initial_data(ratings: List[Rating]) -> None`

加载初始数据并训练模型。

**参数**:
- `ratings`: 初始评分列表

**示例**:
```python
await trainer.load_initial_data(initial_ratings)
```

---

#### `add_ratings(new_ratings: List[Rating]) -> None`

添加新评分,自动检查是否触发重训练。

**参数**:
- `new_ratings`: 新评分列表

**示例**:
```python
await trainer.add_ratings(new_ratings)
```

---

#### `trigger_retrain() -> None`

手动触发重训练。

**示例**:
```python
await trainer.trigger_retrain()
```

---

#### `get_trainer_info() -> dict`

获取训练器状态信息。

**返回**:
```python
{
    "is_training": bool,  # 是否正在训练
    "last_train_time": str,  # 上次训练时间(ISO格式)
    "total_ratings": int,  # 总评分数
    "pending_ratings": int,  # 待训练评分数
    "config": {
        "threshold_ratings": int,  # 评分阈值
        "threshold_time": int,  # 时间阈值(秒)
        "auto_retrain": bool,  # 是否自动重训练
    },
}
```

## 数据模型

### RatingMatrix

评分矩阵的统一表示。

**属性**:
```python
user_ids: np.ndarray  # 用户ID数组
item_ids: np.ndarray  # 物品ID数组
ratings: np.ndarray  # 评分数组
user_map: Dict[int, int]  # 用户ID映射
item_map: Dict[int, int]  # 物品ID映射
```

**方法**:
- `from_ratings(ratings: List[Rating])`: 从评分列表构建
- `to_dataframe()`: 转换为 DataFrame
- `to_sparse()`: 转换为稀疏矩阵
- `to_numpy()`: 转换为 NumPy 数组

### Rating

单个评分记录。

**属性**:
```python
user_id: int  # 用户ID
item_id: int  # 物品ID
rating: float  # 评分 (1.0-5.0)
timestamp: datetime  # 评分时间
```

### Item

物品信息。

**属性**:
```python
item_id: int  # 物品ID
name: str  # 物品名称
category: str  # 分类
metadata: Dict[str, Any]  # 元数据
```

## 配置参数

### MFConfig

MF 算法配置参数。

```python
MFConfig(
    n_latent_factors: int = 50,      # 潜在因子数量
    learning_rate: float = 0.01,     # 学习率
    reg_param: float = 0.01,         # L2正则化参数
    n_iterations: int = 100,         # 训练迭代次数
)
```

### ServiceConfig

推荐服务配置参数。

```python
ServiceConfig(
    cache_ttl: int = 300,            # 缓存过期时间(秒)
    max_batch_size: int = 100,       # 最大批量大小
    timeout: float = 10.0,           # 请求超时时间(秒)
)
```

### TrainerConfig

训练器配置参数。

```python
TrainerConfig(
    retrain_threshold_ratings: int = 100,   # 新评分数阈值
    retrain_threshold_time: int = 300,      # 时间阈值(秒)
    enable_auto_retrain: bool = True,       # 启用自动重训练
)
```

## 使用场景

### 场景 1: 离线批量训练

适用于定期批量更新模型的场景。

```python
# 只使用 Service,不使用 Trainer
algorithm = MFRecommender(MFConfig())
service = RecommendationService(algorithm)

# 定期重新训练
while True:
    # 收集一段时间的数据
    new_data = collect_ratings()
    data = RatingMatrix.from_ratings(new_data)

    # 重新训练
    await service.fit(data)

    # 保存模型
    await service.save_model(f"model_{timestamp}.pkl")

    # 等待下次更新
    await asyncio.sleep(3600)
```

### 场景 2: 实时增量更新

适用于需要实时响应用户行为的场景。

```python
# 使用 Service + Trainer
algorithm = MFRecommender(MFConfig())
service = RecommendationService(algorithm)
trainer = IncrementalTrainer(
    service,
    TrainerConfig(
        retrain_threshold_ratings=50,  # 50条新评分触发
        retrain_threshold_time=300,  # 或5分钟触发
    ),
)

# 初始化
await trainer.load_initial_data(initial_ratings)


# 实时添加新评分
async def on_new_rating(rating: Rating):
    await trainer.add_ratings([rating])
    # 自动检查是否需要重训练
```

### 场景 3: 批量推荐服务

适用于需要为多个用户同时生成推荐的场景。

```python
# 并发为多个用户生成推荐
async def generate_feeds(user_ids: List[int]):
    results = await service.batch_recommend(user_ids, n=20)

    for user_id, recommendations in results.items():
        # 为每个用户准备 Feed
        feed = prepare_feed(user_id, recommendations)
        await send_to_user(user_id, feed)
```

### 场景 4: A/B 测试

适用于对比不同算法或参数的场景。

```python
# 创建两个服务
service_a = RecommendationService(MFRecommender(MFConfig(n_latent_factors=50)))
service_b = RecommendationService(MFRecommender(MFConfig(n_latent_factors=100)))

# 同时训练
await service_a.fit(data)
await service_b.fit(data)

# 对比推荐结果
recs_a = await service_a.recommend(user_id, n=10)
recs_b = await service_b.recommend(user_id, n=10)
```

## 使用说明

### 环境要求

- Python 3.11+
- PyTorch
- pandas, numpy
- pydantic

### 安装依赖

```bash
pip install torch pandas numpy pydantic
```

### 冷启动策略

**新用户**:
- 返回热门物品 (基于 `平均评分 × log(评分数+1)`)
- 累积评分后自动纳入训练

**新物品**:
- 返回默认评分 2.5
- 累积足够评分后纳入训练

### 性能指标

**训练性能**:

| 数据规模 | 用户数 | 物品数 | 评分数 | 训练时间 |
|---------|--------|--------|--------|---------|
| 小 | 100 | 1K | 10K | <10s |
| 中 | 1K | 5K | 100K | <30s |
| 大 | 5K | 10K | 500K | <2min |

**推荐延迟**:
- 单个推荐请求: <100ms (有缓存: <10ms)
- 并发推荐 (100 QPS): 平均延迟 <150ms

### 最佳实践

1. **模型持久化**: 定期保存模型,避免重新训练
2. **缓存管理**: 合理设置 `cache_ttl`,平衡新鲜度和性能
3. **批量推荐**: 优先使用 `batch_recommend` 提高效率
4. **参数调优**: 根据数据规模调整 `n_latent_factors` 和 `n_iterations`
5. **增量训练**: 根据数据流速度调整触发阈值
6. **并发控制**: 避免同时训练多个模型

### 限制和注意事项

- 所有 Service 和 Trainer API 都是异步的,必须在 async 函数中调用
- 训练期间推荐服务不会中断,但使用的是旧模型
- 大数据集训练时注意内存占用
- 冷启动用户的推荐质量可能较低

### 故障排查

**训练失败**:
- 检查评分数据是否为空
- 检查 MFConfig 参数是否合理
- 查看日志获取详细错误信息

**推荐为空**:
- 检查模型是否已训练 (`get_algorithm_info()`)
- 检查用户ID是否存在
- 新用户会返回热门物品

**重训练不触发**:
- 检查 `enable_auto_retrain` 是否为 True
- 检查是否达到触发阈值
- 查看 `get_trainer_info()` 中的 `pending_ratings`

**缓存问题**:
- 使用 `clear_cache()` 清空缓存
- 检查 `cache_ttl` 设置是否合理
- 查看 `get_cache_stats()` 了解缓存状态

## 扩展开发

### 添加新算法

1. 继承 `RecommenderAlgorithm` 类
2. 实现 5 个核心方法
3. 创建配置类 (可选)
4. 在 `__init__.py` 中导出

**示例**:
```python
from .core import RecommenderAlgorithm, RatingMatrix


class MyRecommender(RecommenderAlgorithm):
    def fit(self, data: RatingMatrix) -> None:
        # 训练逻辑
        pass

    def predict(self, user_id: int, item_id: int) -> float:
        # 预测逻辑
        pass

    def recommend(
        self, user_id: int, n: int, exclude_ids: Set[int]
    ) -> List[Tuple[int, float]]:
        # 推荐逻辑
        pass

    def get_algorithm_name(self) -> str:
        return "MyRecommender"
```

### 自定义训练策略

继承 `IncrementalTrainer` 并重写 `_should_retrain()`:

```python
class CustomTrainer(IncrementalTrainer):
    def _should_retrain(self) -> bool:
        # 自定义触发逻辑
        if my_custom_condition():
            return True
        return super()._should_retrain()
```

---
