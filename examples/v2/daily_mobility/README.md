# Daily Mobility Example

本目录整理自 `agentsociety_data/daily_mobility_experiment`，只保留可协作的模拟配置生成代码、评估代码和小型 groundtruth 数据。运行输出、SQLite、日志、agent workspace 都写入 `tmp/`，默认不加入 git。

## 目录

| 路径 | 用途 | 是否适合提交 |
|---|---|---|
| `init/config_params.py` | 生成 `init_config.json` 和 `steps.yaml` | 是 |
| `run_all.py` | 一站式生成配置、world description 检查、仿真、指标计算 | 是 |
| `tools/eval_metrics.py` | 根据 `mobility_metrics_export.json` 和问卷 artifacts 计算指标 | 是 |
| `data/groundtruth/` | DailyMobility 指标真值小数据 | 是 |
| `tmp/init/` | 生成的配置文件 | 否 |
| `tmp/run/` | CLI 输出、日志、数据库、agent workspace | 否 |

## 生成配置

```bash
DAILY_MOBILITY_PRESET=smoke \
DAILY_MOBILITY_NUM_AGENTS=2 \
uv run python examples/v2/daily_mobility/init/config_params.py
```

生成文件：

- `examples/v2/daily_mobility/tmp/init/init_config.json`
- `examples/v2/daily_mobility/tmp/init/steps.yaml`

生成的 agent 类型为 `PersonAgent`，并使用 `max_react_turns`。
环境模块为 `MobilitySpace`。

## 一站式脚本

只生成配置并测试 world description：

```bash
uv run python examples/v2/daily_mobility/run_all.py \
  --stage world-description \
  --preset smoke \
  --num-agents 2
```

本地没有可用 LLM 时，可以只验证环境模块加载和 world description 输入摘要：

```bash
AGENTSOCIETY_LLM_API_KEY=dummy \
AGENTSOCIETY_LLM_API_BASE=http://localhost/v1 \
uv run python examples/v2/daily_mobility/run_all.py \
  --stage world-description \
  --preset smoke \
  --num-agents 2 \
  --world-description-dry-run
```

完整 smoke 流程：

```bash
uv run python examples/v2/daily_mobility/run_all.py \
  --stage all \
  --preset smoke \
  --num-agents 2
```

## 运行仿真

```bash
uv run python -m agentsociety2.society.cli \
  --config examples/v2/daily_mobility/tmp/init/init_config.json \
  --steps examples/v2/daily_mobility/tmp/init/steps.yaml \
  --run-dir examples/v2/daily_mobility/tmp/run \
  --experiment-id daily_mobility \
  --log-file examples/v2/daily_mobility/tmp/run/output.log
```

地图文件默认从 `DAILY_MOBILITY_MAP_PATH`、`AGENTSOCIETY_HOME_DIR` 或仓库根目录的 `agentsociety_data/` 查找。`.pb` 地图文件不纳入 git。

## 计算指标

```bash
uv run python examples/v2/daily_mobility/tools/eval_metrics.py
```

默认读取：

- run 目录：`examples/v2/daily_mobility/tmp/run`
- groundtruth：`examples/v2/daily_mobility/data/groundtruth`

输出：

- `examples/v2/daily_mobility/tmp/run/scores.json`

## 性能剖析与运行取舍

MobilitySpace 的观察接口共用一次附近 POI 查询，再汇总各类别；候选距离
使用 Shapely 批量计算。路由 HTTP 连接在环境生命周期内复用。

默认在环境进程内执行计算，适用于自有独立容器里的仿真。需要为计算设置
独立进程、硬执行期限和内存限制时，可为一次实验开启：

```bash
AGENTSOCIETY_CODE_EXEC_BACKEND=process \
uv run python examples/v2/daily_mobility/run_all.py \
  --stage all --preset smoke --num-agents 2
```

设为 `inprocess` 或省略该配置即可使用默认的进程内执行。两种模式均保留
代码许可、工具只读约束、Python 循环检查及写后停止重试。进程内模式使用
容器的 CPU/内存限制和作业总期限管理原生计算，工具参数与响应沿用 Python 对象。

评估时分别记录模型等待、代码执行、POI 查询、路径请求、环境推进和检查点
耗时；同时核对移动结果与模型调用、Token、重试和响应复用。

关键实测指标和测量条件记录在对应提交中。逐次数据、资源采样和完整实验
材料保存在本地 `benchmark_results/`，由 Git 忽略。
