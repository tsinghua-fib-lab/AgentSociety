"""城市地图：从 protobuf 解析车道/路口/道路/AOI/POI，并构建 Shapely 几何与空间索引。"""

import logging
import os
import pickle
from copy import deepcopy
from typing import Any, Literal, TypeVar

import numpy as np
import pyproj
import shapely
import stringcase
from geojson import Feature
from google.protobuf import json_format
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.message import Message
from pycityproto.city.geo.v2 import geo_pb2
from pycityproto.city.map.v2 import map_pb2
from pycityproto.city.routing.v2 import routing_pb2
from pycityproto.city.routing.v2 import routing_service_pb2 as routing_service
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring, unary_union

from agentsociety2.contrib.env.mobility_space.utils import POI_CATG_DICT

__all__ = ["Map"]

T = TypeVar("T", bound=Message)


def dict2pb(d: dict, pb: T) -> T:
    """将字典解析为给定的 protobuf 消息（忽略未知字段）。

    :param d: 与 protobuf JSON 映射一致的源字典。
    :param pb: 待填充的 protobuf 实例。
    :returns: 填充后的同一 ``pb`` 实例。
    """
    return json_format.ParseDict(d, pb, ignore_unknown_fields=True)


class Map:
    """解析 ``map_pb2.Map`` 并提供查询与 GeoJSON 导出。

    解析后设置的实例属性（值为 ``dict`` 等，含 ``shapely_xy`` / ``shapely_lnglat`` 等派生字段）：

    :ivar header: 地图元数据（名称、边界、PROJ 投影串等）。
    :ivar juncs: 路口 ``id ->`` 记录（``lane_ids``、``center`` 等）。
    :ivar lanes: 车道 ``id ->`` 记录（``type``、``turn``、``center_line``、前后继等）。
    :ivar roads: 道路 ``id ->`` 记录（``lane_ids``、``driving_lane_ids``、``length`` 等）。
    :ivar aois: AOI ``id ->`` 记录（``positions``、``poi_ids``、``urban_land_use`` 等）。
    :ivar pois: POI ``id ->`` 记录（``name``、``category``、``position``、``aoi_id`` 等）。
    :ivar projector: ``pyproj.Proj``，用于 xy 与经纬度互转。
    :ivar poi_cate: 类别字典，见 :data:`~agentsociety2.contrib.env.mobility_space.utils.const.POI_CATG_DICT`。
    """

    def __init__(self, pb_path: str) -> None:
        """
        :param pb_path: ``Map`` protobuf 文件路径；若存在 ``{pb_path}.cache`` 则优先读缓存，否则解析 pb 并写缓存。
        """
        logging.debug("Map init")
        map_data = None
        # 1. try to load from cache
        cache_path = pb_path + ".cache"
        if os.path.exists(cache_path):
            logging.debug("Start load cache file")
            with open(cache_path, "rb") as f:
                map_data = pickle.load(f)
            logging.debug("Finish load cache file")

        if map_data is None:
            logging.debug("No cache file found, start parse pb file")
            try:
                with open(pb_path, "rb") as f:
                    pb = map_pb2.Map().FromString(f.read())
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"Map file not found: {pb_path}. "
                    f"You can try downloading it via `agentsociety-use-dataset skill`."
                ) from None
            jsons = []
            for field in pb.DESCRIPTOR.fields:
                class_name = stringcase.spinalcase(field.message_type.name)
                if field.label == field.LABEL_REPEATED:
                    for pb_field in getattr(pb, field.name):
                        data = MessageToDict(
                            pb_field,
                            always_print_fields_with_no_presence=True,
                            preserving_proto_field_name=True,
                            use_integers_for_enums=True,
                        )
                        jsons.append({"class": class_name, "data": data})
                else:
                    data = MessageToDict(
                        getattr(pb, field.name),
                        preserving_proto_field_name=True,
                        use_integers_for_enums=True,
                    )
                    jsons.append({"class": class_name, "data": data})
            map_data = self._parse_map(jsons)
            logging.debug("Finish parse pb file")
            logging.debug("Start save cache file")
            with open(cache_path, "wb") as f:
                pickle.dump(map_data, f)
            logging.debug("Finish save cache file")

        self.header: dict = map_data["header"]
        self.juncs: dict[int, dict] = map_data["juncs"]
        self.lanes: dict[int, dict] = map_data["lanes"]
        self.roads: dict[int, dict] = map_data["roads"]
        self.aois: dict[int, dict] = map_data["aois"]
        self.pois: dict[int, dict] = map_data["pois"]
        self.projector: pyproj.Proj = map_data["projector"]
        (
            self._aoi_tree,
            self._aoi_list,
            self._poi_tree,
            self._poi_list,
            self._driving_lane_tree,
            self._driving_lane_list,
            self._walking_lane_tree,
            self._walking_lane_list,
        ) = self._build_geo_index()

        self.poi_cate = POI_CATG_DICT

    def _parse_map(self, m: list[Any]) -> dict[str, Any]:
        """将中间 JSON 列表解析为内部地图结构并派生几何。"""
        header = None
        juncs = {}
        roads = {}
        lanes = {}
        aois = {}
        pois = {}
        for d in m:
            if "_id" in d:
                del d["_id"]
            t = d["class"]
            data = d["data"]
            if t == "lane":
                lanes[data["id"]] = data
            elif t == "junction":
                juncs[data["id"]] = data
            elif t == "road":
                roads[data["id"]] = data
            elif t == "aoi":
                aois[data["id"]] = data
            elif t == "poi":
                pois[data["id"]] = data
            elif t == "header":
                header = data
        assert header is not None, "header is None"
        logging.debug("Finish parse map data - classify")
        projector = pyproj.Proj(header["projection"])  # type: ignore
        # 处理lane的Geos
        logging.debug("Start process lane geos")
        for lane in lanes.values():
            nodes = np.array(
                [[one["x"], one["y"]] for one in lane["center_line"]["nodes"]]
            )
            lane["shapely_xy"] = LineString(nodes)
            lngs, lats = projector(nodes[:, 0], nodes[:, 1], inverse=True)
            lane["shapely_lnglat"] = LineString(list(zip(lngs, lats, strict=False)))
        logging.debug("Finish process lane geos")
        # 处理road的Geos和其他属性
        logging.debug("Start process road geos")
        for road in roads.values():
            lane_ids = road["lane_ids"]
            driving_lane_ids = [lid for lid in lane_ids if lanes[lid]["type"] == 1]
            road["driving_lane_ids"] = driving_lane_ids
            center_lane_id = lane_ids[len(driving_lane_ids) // 2]
            center_lane = lanes[center_lane_id]
            road["length"] = center_lane["length"]
            road["max_speed"] = center_lane["max_speed"]
            road["shapely_xy"] = center_lane["shapely_xy"]
            road["shapely_lnglat"] = center_lane["shapely_lnglat"]
        logging.debug("Finish process road geos")
        # 处理Aoi的Geos
        logging.debug("Start process aoi geos")
        for aoi in aois.values():
            if "area" not in aoi:
                # 不是多边形aoi
                aoi["shapely_xy"] = Point(
                    aoi["positions"][0]["x"], aoi["positions"][0]["y"]
                )
            else:
                aoi["shapely_xy"] = Polygon(
                    [(one["x"], one["y"]) for one in aoi["positions"]]
                )
            xys = np.array([[one["x"], one["y"]] for one in aoi["positions"]])
            lngs, lats = projector(xys[:, 0], xys[:, 1], inverse=True)
            lnglat_positions = list(zip(lngs, lats, strict=False))
            if "area" not in aoi:
                aoi["shapely_lnglat"] = Point(lnglat_positions[0])
            else:
                aoi["shapely_lnglat"] = Polygon(lnglat_positions)
        logging.debug("Finish process aoi geos")
        # 处理Poi的Geos
        logging.debug("Start process poi geos")
        for poi in pois.values():
            poi["category"] = poi["category"].split("|")
            point = Point(poi["position"]["x"], poi["position"]["y"])
            poi["shapely_xy"] = point
            lng, lat = projector(point.x, point.y, inverse=True)
            poi["shapely_lnglat"] = Point([lng, lat])
        logging.debug("Finish process poi geos")
        # 为junction解算大致的中心点
        logging.debug("Start calculate junction center")
        for junc in juncs.values():
            lane_shapelys = [
                lanes[lane_id]["shapely_xy"] for lane_id in junc["lane_ids"]
            ]
            geos = unary_union(lane_shapelys)
            center = geos.centroid
            junc["center"] = {"x": center.x, "y": center.y}
            # 计算中心点的经纬度坐标
            lng, lat = projector(center.x, center.y, inverse=True)
            junc["center_lnglat"] = {"lng": lng, "lat": lat}
        logging.debug("Finish calculate junction center")

        return {
            "header": header,
            "juncs": juncs,
            "roads": roads,
            "lanes": lanes,
            "aois": aois,
            "pois": pois,
            "projector": projector,
        }

    def _build_geo_index(self):
        """为 AOI、POI、行车道、人行道构建 :class:`shapely.STRtree` 索引。"""
        aoi_list = list(self.aois.values())
        aoi_tree = shapely.STRtree([aoi["shapely_xy"] for aoi in aoi_list])
        poi_list = list(self.pois.values())
        poi_tree = shapely.STRtree([poi["shapely_xy"] for poi in poi_list])
        driving_lane_list = [
            lane
            for lane in self.lanes.values()
            if lane["type"] == 1  # driving
        ]
        driving_lane_tree = shapely.STRtree(
            [lane["shapely_xy"] for lane in driving_lane_list]
        )
        walking_lane_list = [
            lane
            for lane in self.lanes.values()
            if lane["type"] == 2  # walking
        ]
        walking_lane_tree = shapely.STRtree(
            [lane["shapely_xy"] for lane in walking_lane_list]
        )
        logging.debug("Finish build geo index")
        return (
            aoi_tree,
            aoi_list,
            poi_tree,
            poi_list,
            driving_lane_tree,
            driving_lane_list,
            walking_lane_tree,
            walking_lane_list,
        )

    def _get_lane_s(self, position: geo_pb2.Position, lane_id: int) -> float:
        """计算 ``position`` 在 ``lane_id`` 对应车道中心线上的弧长参数 ``s``。

        :param position: 含 ``aoi_position`` 或 ``lane_position`` 的位置。
        :param lane_id: 车道 ID。
        :returns: 车道上的 ``s``（与 proto 定义一致）。
        :raises AssertionError: ``aoi`` 内找不到该车道连接，或 ``position`` 无有效 oneof 字段时。
        """
        # 处理起点处的截断
        if position.HasField("aoi_position"):
            aoi_id = position.aoi_position.aoi_id
            aoi = self.aois[aoi_id]
            ss = [
                p["s"]
                for p in aoi["walking_positions"] + aoi["driving_positions"]
                if p["lane_id"] == lane_id
            ]
            assert len(ss) == 1, f"lane {lane_id} not found in aoi {aoi_id}"
            return ss[0]
        elif position.HasField("lane_position"):
            return position.lane_position.s
        else:
            raise AssertionError(f"position {position} has no valid field")

    def _get_driving_geo(self, road_id: int):
        """由机动车道路 ID 得到末段行车道 ID 及其中心线几何（xy）。

        :param road_id: 道路 ID。
        :returns: ``(lane_id, shapely_xy LineString)``。
        """
        road = self.roads[road_id]
        aoi_lane_id = road["driving_lane_ids"][-1]
        geo: LineString = road["shapely_xy"]
        return aoi_lane_id, geo

    def _get_walking_geo(self, segment: routing_pb2.WalkingRouteSegment):
        """由步行导航路段得到车道 ID 及中心线几何（按行进方向可能取反）。

        :param segment: 步行路径中的一段。
        :returns: ``(lane_id, shapely_xy LineString)``。
        """
        lane_id = segment.lane_id
        direction = segment.moving_direction
        geo: LineString = self.lanes[lane_id]["shapely_xy"]
        if direction == routing_pb2.MOVING_DIRECTION_BACKWARD:
            geo = geo.reverse()
        return lane_id, geo

    def lnglat2xy(self, lng: float, lat: float) -> tuple[float, float]:
        """WGS84 经纬度转地图投影 xy。

        :param lng: 经度（度）。
        :param lat: 纬度（度）。
        :returns: ``(x, y)`` 投影坐标。
        """
        return self.projector(lng, lat)

    def xy2lnglat(self, x: float, y: float) -> tuple[float, float]:
        """地图投影 xy 转 WGS84 经纬度。

        :param x: 投影 x。
        :param y: 投影 y。
        :returns: ``(lng, lat)``，单位度。
        """
        return self.projector(x, y, inverse=True)

    def position2xy(
        self, position: geo_pb2.Position | dict[str, Any]
    ) -> tuple[float, float]:
        """将 ``Position`` 转为地图投影 xy。

        :param position: ``geo_pb2.Position`` 或可 ``ParseDict`` 的字典。
        :returns: ``(x, y)``；AOI 内位置取 AOI 几何质心，车道上位置按 ``s`` 插值。
        :raises AssertionError: oneof 无有效字段时。
        """

        # 如果position是dict，则转换为geo_pb2.Position
        if isinstance(position, dict):
            position = dict2pb(position, geo_pb2.Position())
        if position.HasField("aoi_position"):
            aoi_id = position.aoi_position.aoi_id
            aoi = self.aois[aoi_id]
            # 计算aoi的中心点
            center = aoi["shapely_xy"].centroid
            return center.x, center.y
        elif position.HasField("lane_position"):
            lane_id = position.lane_position.lane_id
            s = position.lane_position.s
            lane = self.lanes[lane_id]
            point = lane["shapely_xy"].interpolate(s)
            return point.x, point.y
        else:
            raise AssertionError(f"position {position} has no valid field")

    def get_header(self):
        """:returns: 地图 ``header`` 字典。"""
        return self.header

    def get_aoi(self, id: int, include_unused: bool = False) -> Any | None:
        """按 ID 查询 AOI（深拷贝）。

        :param id: AOI ID。
        :param include_unused: 为 ``False`` 时删去部分冗余/外部缓存字段。
        :returns: AOI 字典；不存在则为 ``None``。
        """
        doc = self.aois.get(id)
        if doc is None:
            return None
        doc = deepcopy(doc)
        if not include_unused:
            del doc["type"]
            if "external" in doc:
                if "driving_distances" in doc["external"]:
                    del doc["external"]["driving_distances"]
                if "driving_lane_project_point" in doc["external"]:
                    del doc["external"]["driving_lane_project_point"]
                if "walking_distances" in doc["external"]:
                    del doc["external"]["walking_distances"]
                if "walking_lane_project_point" in doc["external"]:
                    del doc["external"]["walking_lane_project_point"]
        return doc

    def get_poi(self, id: int, include_unused: bool = False) -> Any | None:
        """按 ID 查询 POI（深拷贝）。

        :param id: POI ID。
        :param include_unused: 预留；当前未裁剪额外字段。
        :returns: POI 字典；不存在则为 ``None``。
        """
        doc = self.pois.get(id)
        if doc is None:
            return None
        doc = deepcopy(doc)
        return doc

    def get_lane(self, id: int, include_unused: bool = False) -> Any | None:
        """按 ID 查询车道（深拷贝）。

        :param id: 车道 ID。
        :param include_unused: 为 ``False`` 时移除 ``left_border_line`` 等重型字段。
        :returns: 车道字典；不存在则为 ``None``。
        """
        doc = self.lanes.get(id)
        if doc is None:
            return None
        doc = deepcopy(doc)
        if not include_unused:
            if "left_border_line" in doc:
                del doc["left_border_line"]
            if "right_border_line" in doc:
                del doc["right_border_line"]
            if "overlaps" in doc:
                del doc["overlaps"]
        return doc

    def get_road(self, id: int, include_unused: bool = False) -> Any | None:
        """按 ID 查询道路（深拷贝）。

        :param id: 道路 ID。
        :param include_unused: 预留；当前未裁剪额外字段。
        :returns: 道路字典；不存在则为 ``None``。
        """
        doc = self.roads.get(id)
        if doc is None:
            return None
        doc = deepcopy(doc)
        return doc

    def get_junction(self, id: int, include_unused: bool = False) -> Any | None:
        """按 ID 查询路口（深拷贝）。

        :param id: 路口（junction）ID。
        :param include_unused: 为 ``False`` 时移除 ``external``、``driving_lane_groups`` 等。
        :returns: 路口字典；不存在则为 ``None``。
        """
        doc = self.juncs.get(id)
        if doc is None:
            return None
        doc = deepcopy(doc)
        if not include_unused:
            if "external" in doc:
                del doc["external"]
            if "driving_lane_groups" in doc:
                del doc["driving_lane_groups"]
        return doc

    def export_aoi_center_as_geojson(
        self,
        id: int,
        properties: dict[str, Any] | Literal["auto"] = "auto",
    ) -> dict:
        """将 AOI 质心导出为 GeoJSON Feature 字典。

        :param id: AOI ID。
        :param properties: Feature 的 ``properties``；``"auto"`` 时填充 ``point_type``、``aoi_type``、``poi_ids`` 等。
        :returns: 可 JSON 序列化的 GeoJSON dict。
        """
        aoi = self.get_aoi(id)
        assert aoi is not None, f"aoi {id} not found"
        geometry = aoi["shapely_lnglat"].centroid
        if properties == "auto":
            properties = {
                "point_type": "aoi",
                "id": str(id),
                "aoi_type": str(aoi.get("land_use", 0)),
                "poi_ids": [str(pid) for pid in aoi["poi_ids"]],
            }
        feature = Feature(id=id, geometry=geometry, properties=properties)
        return dict(feature)

    def export_aoi_as_geojson(
        self, id: int, properties: dict[str, Any] | Literal["auto"] = "auto"
    ) -> dict:
        """将 AOI 多边形导出为 GeoJSON Feature 字典。

        :param id: AOI ID。
        :param properties: Feature 的 ``properties``；``"auto"`` 时填充 ``aoi_type``、``poi_ids`` 等。
        :returns: 可 JSON 序列化的 GeoJSON dict。
        """
        aoi = self.get_aoi(id)
        assert aoi is not None, f"aoi {id} not found"
        geometry = aoi["shapely_lnglat"]
        if properties == "auto":
            properties = {
                "aoi_type": str(aoi.get("land_use", 0)),
                "poi_ids": [str(pid) for pid in aoi.get("poi_ids", [])],
            }
        feature = Feature(id=id, geometry=geometry, properties=properties)
        return dict(feature)

    def export_poi_as_geojson(
        self, id: int, properties: dict[str, Any] | Literal["auto"] = "auto"
    ) -> dict:
        """将 POI 点导出为 GeoJSON Feature 字典。

        :param id: POI ID。
        :param properties: Feature 的 ``properties``；``"auto"`` 时填充 ``point_type``、``poi_type``、``name`` 等。
        :returns: 可 JSON 序列化的 GeoJSON dict。
        """
        poi = self.get_poi(id)
        assert poi is not None, f"poi {id} not found"
        geometry = poi["shapely_lnglat"]
        if properties == "auto":
            properties = {
                "point_type": "poi",
                "id": str(id),
                "poi_type": poi["category"],
                "name": poi["name"],
                "address": "",
            }
        feature = Feature(id=id, geometry=geometry, properties=properties)
        return dict(feature)

    def export_lane_as_geojson(
        self, id: int, properties: dict[str, Any] | Literal["auto"] = "auto"
    ) -> dict:
        """将车道中心线导出为 GeoJSON Feature 字典。

        :param id: 车道 ID。
        :param properties: Feature 的 ``properties``；``"auto"`` 时填充 ``lane_type``、``lane_turn``、``parent_id``、``max_speed``。
        :returns: 可 JSON 序列化的 GeoJSON dict。
        """
        lane = self.get_lane(id)
        assert lane is not None, f"lane {id} not found"
        geometry = lane["shapely_lnglat"]
        if properties == "auto":
            properties = {
                "id": str(id),
                "lane_type": str(lane["type"]),
                "lane_turn": str(lane["turn"]),
                "parent_id": str(lane["parent_id"]),
                "max_speed": lane["max_speed"],
            }
        feature = Feature(id=id, geometry=geometry, properties=properties)
        return dict(feature)

    def export_road_as_geojson(
        self, id: int, properties: dict[str, Any] | None = None
    ) -> dict:
        """将道路几何导出为 GeoJSON Feature 字典。

        :param id: 道路 ID。
        :param properties: Feature 的 ``properties``；默认 ``None`` 视为 ``{}``。
        :returns: 可 JSON 序列化的 GeoJSON dict。
        """
        if properties is None:
            properties = {}
        road = self.get_road(id)
        assert road is not None, f"road {id} not found"
        geometry = road["shapely_lnglat"]
        feature = Feature(id=id, geometry=geometry, properties=properties)
        return dict(feature)

    def _route_to_xys(
        self,
        route_req: routing_service.GetRouteRequest | dict,
        route_res: routing_service.GetRouteResponse | dict,
    ) -> np.ndarray:
        """将驾车/步行导航结果转为 xy 坐标折线顶点数组（不含最后经纬度变换）。

        :param route_req: ``GetRouteRequest`` 或可 ``ParseDict`` 的字典。
        :param route_res: ``GetRouteResponse`` 或可 ``ParseDict`` 的字典。
        :returns: ``(N, 2)`` 的 ``float`` 数组，列为 ``(x, y)``。
        :raises AssertionError: 路线类型不支持或 journey 类型不匹配时。
        """
        if not isinstance(route_req, routing_service.GetRouteRequest):
            route_req = ParseDict(route_req, routing_service.GetRouteRequest())
        if not isinstance(route_res, routing_service.GetRouteResponse):
            route_res = ParseDict(route_res, routing_service.GetRouteResponse())
        assert route_req.type in (
            routing_pb2.ROUTE_TYPE_DRIVING,
            routing_pb2.ROUTE_TYPE_WALKING,
        ), f"route type {route_req.type} not supported"
        is_walk = route_req.type == routing_pb2.ROUTE_TYPE_WALKING
        coordinates = []
        for journey in route_res.journeys:
            if is_walk:
                assert journey.type == routing_pb2.JOURNEY_TYPE_WALKING
                route_ids = list(journey.walking.route)
            else:
                assert journey.type == routing_pb2.JOURNEY_TYPE_DRIVING
                route_ids = list(journey.driving.road_ids)
            if not route_ids:
                continue
            lane_id, geo = (
                self._get_walking_geo(route_ids[0])
                if is_walk
                else self._get_driving_geo(route_ids[0])
            )
            start_s = self._get_lane_s(route_req.start, lane_id)
            if len(route_ids) == 1:
                end_s = self._get_lane_s(route_req.end, lane_id)
                geo = substring(geo, start_s, end_s)
            else:
                geo = substring(geo, start_s, geo.length)
            coordinates += list(geo.coords)
            for segment_id in route_ids[1:-1]:
                _, geo = (
                    self._get_walking_geo(segment_id)
                    if is_walk
                    else self._get_driving_geo(segment_id)
                )
                coordinates += list(geo.coords)
            if len(route_ids) > 1:
                lane_id, geo = (
                    self._get_walking_geo(route_ids[-1])
                    if is_walk
                    else self._get_driving_geo(route_ids[-1])
                )
                end_s = self._get_lane_s(route_req.end, lane_id)
                geo = substring(geo, 0, end_s)
                coordinates += list(geo.coords)
        if route_req.start.HasField("aoi_position"):
            aoi_center = self.aois[route_req.start.aoi_position.aoi_id][
                "shapely_xy"
            ].centroid.coords[0]
            coordinates = [aoi_center, *coordinates]
        if route_req.end.HasField("aoi_position"):
            aoi_center = self.aois[route_req.end.aoi_position.aoi_id][
                "shapely_xy"
            ].centroid.coords[0]
            coordinates = [*coordinates, aoi_center]
        coordinates = np.array(coordinates)
        return coordinates

    def export_route_as_geojson(
        self,
        route_req: routing_service.GetRouteRequest | dict,
        route_res: routing_service.GetRouteResponse | dict,
        properties: dict | None = None,
    ) -> dict:
        """将导航请求/响应中的路径导出为 GeoJSON LineString Feature 字典（经纬度）。

        :param route_req: ``GetRouteRequest`` 或可 ``ParseDict`` 的字典。
        :param route_res: ``GetRouteResponse`` 或可 ``ParseDict`` 的字典。
        :param properties: Feature 的 ``properties``；默认 ``None`` 视为 ``{}``。
        :returns: 可 JSON 序列化的 GeoJSON dict。
        """
        if properties is None:
            properties = {}
        if not isinstance(route_req, routing_service.GetRouteRequest):
            route_req = ParseDict(route_req, routing_service.GetRouteRequest())
        if not isinstance(route_res, routing_service.GetRouteResponse):
            route_res = ParseDict(route_res, routing_service.GetRouteResponse())

        coordinates = self._route_to_xys(route_req, route_res)
        # xy -> lnglat
        lngs, lats = self.projector(coordinates[:, 0], coordinates[:, 1], inverse=True)
        geo = LineString(list(zip(lngs, lats, strict=False)))
        feature = Feature(geometry=geo, properties=properties)
        return dict(feature)

    def estimate_route_time(
        self,
        route_req: routing_service.GetRouteRequest | dict,
        route_res: routing_service.GetRouteResponse | dict,
    ) -> float:
        """对导航响应中的各 journey 累加 ETA（秒）。

        :param route_req: ``GetRouteRequest`` 或可 ``ParseDict`` 的字典。
        :param route_res: ``GetRouteResponse`` 或可 ``ParseDict`` 的字典。
        :returns: 总估算时间（秒）；步行/驾车分别对 ``walking.eta`` / ``driving.eta`` 求和。
        """
        if not isinstance(route_req, routing_service.GetRouteRequest):
            route_req = ParseDict(route_req, routing_service.GetRouteRequest())
        if not isinstance(route_res, routing_service.GetRouteResponse):
            route_res = ParseDict(route_res, routing_service.GetRouteResponse())

        is_walk = route_req.type == routing_pb2.ROUTE_TYPE_WALKING
        if is_walk:
            return sum(j.walking.eta for j in route_res.journeys)
        else:
            return sum(j.driving.eta for j in route_res.journeys)

    def query_pois(
        self,
        center: tuple[float, float] | Point,
        radius: float | None = None,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[tuple[Any, float]]:
        """在投影 xy 下按距离查询 POI；类别字符串需出现在 POI 的 ``category`` 列表中。

        :param center: ``(x, y)`` 或 :class:`shapely.geometry.Point`。
        :param radius: 搜索半径（米）；``None`` 表示遍历全图 POI。
        :param category: 非 ``None`` 时仅保留 ``category`` 含该子串的 POI。
        :param limit: 最多返回条数，近者优先。
        :returns: ``(poi_dict, 距离)`` 列表，按距离升序。
        """
        if not isinstance(center, Point):
            center = Point(center)
        if radius is None:
            poi_iter = self._poi_list
        else:
            indices = self._poi_tree.query(center.buffer(radius))
            poi_iter = (self._poi_list[index] for index in indices)

        pois = []
        for poi in poi_iter:
            if category is None or category in poi["category"]:
                distance = center.distance(poi["shapely_xy"])
                pois.append((poi, distance))
        # 按照距离排序
        pois = sorted(pois, key=lambda x: x[1])
        if limit is not None:
            pois = pois[:limit]
        return pois

    def query_aois(
        self,
        center: tuple[float, float] | Point,
        radius: float,
        urban_land_uses: list[str] | None = None,
        limit: int | None = None,
    ) -> list[tuple[Any, float]]:
        """在投影 xy 下按距离查询 AOI，可按 ``urban_land_use`` 过滤。

        :param center: ``(x, y)`` 或 :class:`shapely.geometry.Point`。
        :param radius: 搜索半径（米）。
        :param urban_land_uses: 非 ``None`` 时仅保留 ``urban_land_use`` 属于该集合的 AOI（GB 50137-2011 分类字符串）。
        :param limit: 最多返回条数，近者优先。
        :returns: ``(aoi_dict, 距离)`` 列表，按距离升序。
        """

        if not isinstance(center, Point):
            center = Point(center)
        # 获取半径内的aoi
        indices = self._aoi_tree.query(center.buffer(radius))
        # 过滤掉不满足城市用地条件的aoi
        aois = []
        for index in indices:
            aoi = self._aoi_list[index]
            if (
                urban_land_uses is not None
                and aoi["urban_land_use"] not in urban_land_uses
            ):
                continue
            distance = center.distance(aoi["shapely_xy"])
            aois.append((aoi, distance))
        # 按照距离排序
        aois = sorted(aois, key=lambda x: x[1])
        if limit is not None:
            aois = aois[:limit]
        return aois

    def query_lane(
        self,
        xy: tuple[float, float] | Point,
        radius: float,
        lane_type: int = 1,
    ) -> list[tuple[Any, float, float]]:
        """在投影 xy 下查询附近车道及投影弧长 ``s``。

        :param xy: ``(x, y)`` 或 :class:`shapely.geometry.Point`。
        :param radius: 搜索半径（米）；欧氏距离大于半径的候选会被丢弃。
        :param lane_type: ``1`` 机动车道，``2`` 人行道。
        :returns: ``(lane_dict, s, 距离)`` 列表，按距离升序。
        :raises ValueError: ``lane_type`` 非 ``1``/``2`` 时。
        """

        if not isinstance(xy, Point):
            xy = Point(xy)
        if lane_type == 1:
            indices = self._driving_lane_tree.query(xy.buffer(radius))
            lanes = [self._driving_lane_list[index] for index in indices]
        elif lane_type == 2:
            indices = self._walking_lane_tree.query(xy.buffer(radius))
            lanes = [self._walking_lane_list[index] for index in indices]
        else:
            raise ValueError(f"lane_type {lane_type} not supported")
        result = []  # (lane, s, distance)
        # 计算距离和s坐标
        for lane in lanes:
            distance = xy.distance(lane["shapely_xy"])
            if distance > radius:
                continue
            s = lane["shapely_xy"].project(xy)
            result.append((lane, s, distance))
        # 按距离排序
        result = sorted(result, key=lambda x: x[2])

        return result
