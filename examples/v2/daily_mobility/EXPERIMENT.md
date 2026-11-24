# 北京日常移动实验

在北京路网上使用 PersonAgent 和 MobilitySpace 模拟居民的一日出行。正式实验选择 `benchmark` 预设，每个问卷时段记录主要活动意图。评估使用 `data/groundtruth/` 中的参考分布，比较每日活动意图、访问地点数和回转半径，指标写入运行目录的 `scores.json`。

生成配置、启动仿真和复算指标的命令见 [Daily Mobility 运行说明](README.md)。
