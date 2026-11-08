---
name: mobility
description: 城市移动导航：在路网中移动 agent 到 AOI/POI、搜索周边 POI、用引力模型推荐目的地。必须通过 ask_env 调用 MobilitySpace 工具。
---

# Mobility

MobilitySpace 是一个基于真实城市路网的移动仿真环境。**所有操作必须通过 `ask_env` 自然语言指令执行**，环境路由器会自动将指令转换为 MobilitySpace 工具调用。

## 环境概念

### AOI

Area of Interest，城市功能区（住宅区、商业区、办公区等）。ID 从 `500000000` 开始。每个 person 有 `home_aoi`（家）和 `work_aoi`（工作地）。

### POI

Point of Interest，具体地点（餐厅、咖啡馆、医院、公园等）。ID 从 `700000000` 开始。每个 POI 属于某个 AOI。

### 移动状态

| 状态 | 含义 |
|------|------|
| `idle` | 空闲，可以发起移动 |
| `moving` | 正在沿路网移动中 |

`moving` 状态下再次调用 `move_to` 会打断当前移动，除非确实需要改变目的地，否则不应这样做。

### 位置信息

`get_person` 返回的 `position` 包含 `aoi_id`、`poi_id`、`xy` 坐标、`lnglat` 经纬度、`kind`（`"aoi"` 或 `"lane"`）。

### 移动模式

| 模式 | 典型场景 |
|------|----------|
| `walking` | 短距离（< 1000m） |
| `driving` | 长距离（≥ 1000m） |

行程用时以 `move_to` 返回的 `eta`（仿真秒数）为准，它与环境实际采用的
移动速度一致。不要用固定步行或驾车速度另算到达时间。

### POI 类别

搜索 POI 时可用的类别：

| 一级类别 | 典型二级类别 |
|----------|-------------|
| `restaurant` | bar, cafe, fast_food, restaurant, pub, food_court |
| `outdoor_activity` | park, playground, garden, beach_resort, fishing |
| `indoor_entertainment` | cinema, fitness_centre, bowling_alley, theatre, bar |
| `sports_facility` | sports_centre, swimming_pool, stadium, ice_rink |
| `cultural_and_artistic` | arts_centre, museum, cinema, nightclub |
| `education_institution` | school, university, library, kindergarten |
| `medical_care` | hospital, clinic, pharmacy, dentist |
| `financial_service` | bank, atm |
| `public_service` | police, post_office, townhall |
| `transportation_facility` | parking, bus_station, fuel |
| `children_playground` | playground, summer_camp |
| `nature_and_wildlife_observation` | nature_reserve, bird_hide |
| `water_activity` | swimming_area, marina |
| `other_special_purpose` | marketplace, place_of_worship |

可传入一级类别（如 `restaurant`）匹配该类别下所有二级类别，或传入二级类别（如 `cafe`）精确匹配。

## 可用工具

所有操作通过 `ask_env` 调用：

```
ask_env(instruction="<自然语言指令>", ctx={"id": <your_id>})
```

### get_person（只读，observe）

获取当前状态：位置、状态（idle/moving）、移动目标、附近 POI 概况（按一级类别汇总，含最近 POI 名称和距离）、home_aoi、work_aoi。

```
ask_env(instruction="<observe>", ctx={"id": <your_id>})
```

### recommend_poi_by_gravity（只读）

用引力模型推荐目的地 POI。综合考虑距离和周边同类 POI 密度，比手动搜索更合理。

参数：`person_id`、`category`（POI 类别或 `None` 不限）、`radius`（搜索半径，米）、`exclude_home_work`（是否排除家/工作地的 POI）。

返回推荐 POI 的 id、name、category、distance、aoi_id，以及 `recommended_mode`（建议出行方式）。

### find_nearby_pois（只读）

搜索周边 POI 列表。参数：`x, y`（搜索中心坐标）、`category`（类别或 `None`）、`radius`（搜索半径，米）。返回 id、name、category、distance、aoi_id。

### get_poi（只读）

查询单个 POI 详情。参数：`poi_id`。返回 id、name、category、position、aoi_id。

### move_to（非只读）

发起移动。参数：`person_id`、`aoi_id_or_poi_id`（目标 AOI ID 或 POI ID，≥700000000 为 POI）、`mode`（`"walking"` 或 `"driving"`）。

发起后状态变为 `moving`，后续 step 中自动沿路网移动，到达后自动恢复为 `idle`。

## 示例

### 观察状态

```
ask_env(instruction="<observe>", ctx={"id": 0})
→ home_aoi=500000007, work_aoi=500000123, status=idle, aoi_id=500000007
```

### 去工作地

```
ask_env(instruction="Move person 0 to AOI 500000123 using driving", ctx={"id": 0})
→ status=moving
```

### 搜索餐厅并前往

```
ask_env(instruction="Use recommend_poi_by_gravity for person 0, category restaurant, radius 1200, excluding home/work AOIs. Then move to the recommended POI.", ctx={"id": 0})
→ 推荐 cafe（800m），walking 前往
```

### 回家

```
ask_env(instruction="Move person 0 to AOI 500000007 using driving", ctx={"id": 0})
```

## 约束

1. **所有操作通过 `ask_env`**。不能直接调用 `move_to`、`get_person` 等函数。
2. **`moving` 状态下不要再次 `move_to`**。会打断当前移动，除非确实需要改变目的地。
