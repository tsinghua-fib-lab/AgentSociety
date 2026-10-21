"""Simulator: Urban Simulator"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from subprocess import Popen
from typing import Any, ClassVar, Literal

import aiohttp
import shapely
from pycityproto.city.trip.v2.trip_pb2 import TripMode
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import LineString

from agentsociety2.contrib.env.mobility_space.download_sim import download_binary
from agentsociety2.contrib.env.mobility_space.map import Map
from agentsociety2.contrib.env.mobility_space.utils import (
    find_free_ports,
    wait_for_port,
)
from agentsociety2.env import (
    EnvBase,
    tool,
)
from agentsociety2.env.base import dump_int_map, load_int_map
from agentsociety2.logger import get_logger
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

__all__ = [
    "MobilityPerson",
    "MobilityPersonInit",
    "MobilitySpace",
    "Poi",
    "Position",
    "Target",
]


POI_START_ID = 7_0000_0000
BENCHMARK_SLOT_TICK_SEC = 1800


class PositionInit(BaseModel):
    aoi_id: int = Field(
        ..., description="AOI ID, which is a continuous integer starting from 500000000"
    )
    poi_id: int | None = Field(
        None,
        description="POI ID, which is a continuous integer starting from 700000000 (optional when initializing a person)",
    )


class Position(BaseModel):
    kind: Literal["aoi", "lane"] = Field(
        ..., description="Position kind: 'aoi' or 'lane'"
    )
    aoi_id: int | None = Field(
        None,
        description="AOI ID, which is a continuous integer starting from 500000000",
    )
    poi_id: int | None = Field(
        None,
        description="POI ID, which is a continuous integer starting from 700000000 (optional when initializing a person)",
    )
    poi_category: str | None = Field(
        None,
        description="Second-level POI category when standing at a POI",
    )
    xy: tuple[float, float] = Field(..., description="XY coordinates of the position")
    lnglat: tuple[float, float] = Field(
        ..., description="Lnglat coordinates of the position"
    )


class MobilityPersonInit(BaseModel):
    """Simplified model for initializing MobilityPerson, containing only id and position."""

    id: int = Field(..., description="Person ID")
    position: PositionInit = Field(..., description="The position of the person.")
    work_aoi: int | None = Field(None, description="Work AOI ID for scheduled commute.")
    home_aoi: int | None = Field(None, description="Home AOI ID for scheduled return.")


class Target(BaseModel):
    position: Position = Field(..., description="The target position of the person.")
    mode: Literal["walking", "driving"] = Field(
        ..., description="The mode of the person."
    )
    path: shapely.LineString = Field(..., description="The path of the person.")
    path_s: float = Field(
        ..., description="The s coordinate of the person on the path."
    )
    path_v: float = Field(..., description="The speed of the person on the path.")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class MobilityPerson(BaseModel):
    id: int = Field(..., description="Person ID")
    status: Literal["idle", "moving"] = Field(
        "idle",
        description='Person status. Default: "idle". If person is moving, it should be "moving".',
    )
    position: Position = Field(..., description="The position of the person.")
    target: Target | None = Field(None, description="The target of the person.")
    work_aoi: int | None = Field(None, description="Work AOI ID.")
    home_aoi: int | None = Field(None, description="Home AOI ID.")

    model_config = ConfigDict(arbitrary_types_allowed=True)


# Response models for tool functions
class TargetResponse(BaseModel):
    """Response model for target information (without internal path details)"""

    position: Position = Field(..., description="The target position of the person")
    mode: Literal["walking", "driving"] = Field(
        ..., description="The mode of the person"
    )


class NearbyPoiSummary(BaseModel):
    """Summary of nearby POIs in a category."""

    category: str = Field(..., description="POI first-level category")
    count: int = Field(..., description="Number of POIs in this category nearby")
    nearest_name: str = Field(..., description="Name of the nearest POI")
    nearest_distance: float = Field(..., description="Distance to nearest POI (meters)")


class GetPersonResponse(BaseModel):
    """Response model for get_person() function"""

    id: int = Field(..., description="Person ID")
    status: Literal["idle", "moving"] = Field(..., description="Person status")
    position: Position = Field(..., description="The position of the person")
    target: TargetResponse | None = Field(None, description="The target of the person")
    nearby_pois: list[NearbyPoiSummary] | None = Field(
        None, description="Summary of nearby POIs by category (only when idle)"
    )
    work_aoi: int | None = Field(None, description="Work AOI ID")
    home_aoi: int | None = Field(None, description="Home AOI ID")


class Poi(BaseModel):
    """Point of Interest (POI) model"""

    id: int = Field(..., description="POI ID")
    name: str = Field(..., description="POI name")
    category: str = Field(..., description="POI category")
    position: dict = Field(..., description="POI position (x, y coordinates)")
    aoi_id: int | None = Field(None, description="AOI containing this POI")
    distance: float | None = Field(
        None, description="Distance from search center (only for find_nearby_pois)"
    )


class FindNearbyPoisResponse(BaseModel):
    """Response model for find_nearby_pois() function"""

    pois: list[Poi] = Field(..., description="List of POIs found")


class MobilitySpace(EnvBase):
    """
    The environment, including map data, simulator clients, and environment variables.
    """

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        # Routing is HTTP (aiohttp async POST to a standalone routing server)
        # which handles concurrent requests natively. Mutable state is per-agent
        # (_persons / _person_trajectories / _person_visited_aois are keyed by
        # agent_id) and the map is read-only after init. Different agents never
        # touch the same mutable slot (and one agent never calls concurrently
        # with itself), so concurrent ask calls are safe. Society runs env
        # step() only after all agents' asks complete, so _step_counter never
        # overlaps an ask.
        return True

    # 声明式状态持久化
    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("lng", "REAL"),
        ColumnDef("lat", "REAL"),
        ColumnDef("aoi_id", "INTEGER"),
        ColumnDef("poi_id", "INTEGER"),
        ColumnDef("status", "TEXT"),
    ]

    TRIPMODE2STR: ClassVar[dict] = {
        TripMode.TRIP_MODE_WALK_ONLY: "walking",
        TripMode.TRIP_MODE_DRIVE_ONLY: "driving",
    }

    # ---- Skill Discovery ----

    @classmethod
    def skill_dirs(cls) -> list[Path]:
        skills_dir = Path(__file__).parent / "agent_skills"
        return [skills_dir] if skills_dir.is_dir() else []

    def __init__(
        self,
        file_path: str,
        home_dir: str,
        persons: list[MobilityPersonInit] | list[dict],
        poi_search_limit: int = 10,
    ):
        """
        Initialize the Environment.

        :param file_path: The path to the map file.
        :param home_dir: The home directory of the environment.
        :param persons: The persons to initialize the environment with. Can be a list of MobilityPersonInit objects or dicts.
        :param poi_search_limit: The limit of POIs to search.
        """
        super().__init__()

        # Expand ~ in paths
        file_path = os.path.expanduser(file_path)
        home_dir = os.path.expanduser(home_dir)

        os.makedirs(home_dir, exist_ok=True)
        self._routing_bin_path = download_binary(home_dir)
        self._file_path = file_path
        self._home_dir = home_dir
        self._map = Map(file_path)
        # type annotation
        self._routing_proc: Popen | None = None

        self.poi_id_2_aoi_id: dict[int, int] = {
            poi["id"]: poi["aoi_id"] for poi in self._map._poi_list
        }
        self._poi_search_limit = poi_search_limit
        """limit of POIs to search"""

        self._lock = asyncio.Lock()
        """lock for routing process"""

        # 位置跟踪存储（用于benchmark数据收集）
        self._person_trajectories: dict[int, list[tuple[float, float]]] = {
            p["id"] if isinstance(p, dict) else p.id: [] for p in persons
        }
        """Store trajectory points for each person"""

        self._person_visited_aois: dict[int, set[int]] = {
            p["id"] if isinstance(p, dict) else p.id: set() for p in persons
        }
        """Store visited AOIs for each person"""

        # data: convert MobilityPersonInit or dict to MobilityPerson
        person_objects = []
        for p in persons:
            if isinstance(p, dict):
                # Convert MobilityPersonInit dict to MobilityPerson
                person_init = MobilityPersonInit.model_validate(p)
            else:
                person_init = p
            # convert PositionInit to Position
            if person_init.position.poi_id is not None:
                poi = self._map.get_poi(person_init.position.poi_id)
                assert poi is not None
                x, y = poi["position"]["x"], poi["position"]["y"]
            else:
                aoi = self._map.get_aoi(person_init.position.aoi_id)
                assert aoi is not None
                x, y = aoi["shapely_xy"].centroid.x, aoi["shapely_xy"].centroid.y
            position = Position(
                kind="aoi",
                aoi_id=person_init.position.aoi_id,
                poi_id=person_init.position.poi_id,
                xy=(x, y),
                lnglat=self._map.projector(x, y, inverse=True),
            )
            person_objects.append(
                MobilityPerson(
                    id=person_init.id,
                    status="idle",
                    position=position,
                    target=None,
                    work_aoi=person_init.work_aoi,
                    home_aoi=person_init.home_aoi,
                )
            )

        self._persons: dict[int, MobilityPerson] = {p.id: p for p in person_objects}

        # Step counter for replay data
        self._step_counter: int = 0

    def get_aoi_as_position(self, aoi_id: int) -> Position:
        """
        Get the position of an AOI.
        """
        aoi = self._map.get_aoi(aoi_id)
        assert aoi is not None
        x, y = aoi["shapely_xy"].centroid.x, aoi["shapely_xy"].centroid.y
        return Position(
            kind="aoi",
            aoi_id=aoi_id,
            poi_id=None,
            xy=(x, y),
            lnglat=self._map.projector(x, y, inverse=True),
        )

    def get_poi_as_position(self, poi_id: int) -> Position:
        """
        Get the position of a POI.
        """
        poi = self._map.get_poi(poi_id)
        assert poi is not None
        x, y = poi["position"]["x"], poi["position"]["y"]
        return Position(
            kind="aoi",
            aoi_id=poi["aoi_id"],
            poi_id=poi_id,
            xy=(x, y),
            lnglat=self._map.projector(x, y, inverse=True),
        )

    # ============================================================================
    # Probe Functions for Trajectory and Position Tracking (for Benchmark)
    # ============================================================================

    def record_person_position(self, person_id: int):
        """
        Record the current position of a person to their trajectory.

        :param person_id: The ID of the person
        """
        if person_id not in self._persons:
            return

        # Initialize if not already present（处理动态添加的person）
        if person_id not in self._person_trajectories:
            self._person_trajectories[person_id] = []
        if person_id not in self._person_visited_aois:
            self._person_visited_aois[person_id] = set()

        person = self._persons[person_id]

        # Record XY coordinates
        xy = person.position.xy
        if xy not in self._person_trajectories[person_id]:
            self._person_trajectories[person_id].append(xy)

        # Record AOI if at an AOI
        if person.position.aoi_id is not None:
            self._person_visited_aois[person_id].add(person.position.aoi_id)

    def get_person_trajectory(self, person_id: int) -> list[tuple[float, float]]:
        """
        Get the recorded trajectory of a person.

        :param person_id: The ID of the person

        :returns: List of (x, y) coordinates
        """
        return self._person_trajectories.get(person_id, [])

    def get_person_visited_aois(self, person_id: int) -> set[int]:
        """
        Get the set of AOIs visited by a person.

        :param person_id: The ID of the person

        :returns: Set of AOI IDs
        """
        return self._person_visited_aois.get(person_id, set())

    def get_all_persons_trajectories(self) -> dict[int, list[tuple[float, float]]]:
        """
        Get trajectories for all persons.

        :returns: Dict mapping person_id to list of (x, y) coordinates
        """
        return self._person_trajectories.copy()

    def get_all_persons_visited_aois(self) -> dict[int, set[int]]:
        """
        Get visited AOIs for all persons.

        :returns: Dict mapping person_id to set of AOI IDs
        """
        return {pid: aois.copy() for pid, aois in self._person_visited_aois.items()}

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions and JSON schemas for data models.
        """
        # Get JSON schemas for nested models
        person_init_schema = MobilityPersonInit.model_json_schema()

        description = f"""{cls.__name__}: Mobility management module for urban navigation and location tracking.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters (excluding llm):**
- file_path (str): The path to the map file.
- home_dir (str): The home directory of the environment.
- persons (List[MobilityPersonInit] | List[dict]): List of persons to initialize the environment with. Can be MobilityPersonInit objects or dicts matching the schema.
- poi_search_limit (int, optional): The limit of POIs to search. Default: 10.

**MobilityPersonInit JSON Schema:**
```json
{json.dumps(person_init_schema, indent=2)}
```

**Example initialization config:**
```json
{{
  "file_path": "/path/to/map.pb",
  "home_dir": "/path/to/home",
  "persons": [
    {{
      "id": 1,
      "position": {{
        "aoi_id": 500000000
      }}
    }}
  ],
  "poi_search_limit": 10
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Mobility environment for urban navigation, location tracking, and POI/AOI movement."

    async def init(self, start_datetime: datetime) -> Any:
        """
        Initialize the environment including the routing.
        """
        await super().init(start_datetime)
        # =========================
        # init syncer
        # =========================
        routing_port = find_free_ports()[0]
        self._server_addr = f"localhost:{routing_port}"
        self._routing_proc = Popen(
            [
                self._routing_bin_path,
                "-listen",
                self._server_addr,
                "-map",
                self._file_path,
                "-log-level",
                "warn",
            ],
            env=os.environ,
        )

        get_logger().info(
            f"start routing at {self._server_addr}, PID={self._routing_proc.pid}"
        )

        # Wait for the routing server to start listening
        get_logger().info(
            f"Waiting for routing server to start on port {routing_port}..."
        )
        if not wait_for_port("localhost", routing_port, timeout=30.0):
            # If the port is not available, kill the process and raise an error
            if self._routing_proc.poll() is None:
                self._routing_proc.kill()
            raise RuntimeError(
                f"Routing server failed to start on port {routing_port} within 30 seconds"
            )
        get_logger().info(f"Routing server is ready on {self._server_addr}")

    @property
    def map(self):
        assert self._map is not None, "Map not initialized"
        return self._map

    @property
    def projector(self):
        return self._map.projector

    def _get_around_pois(
        self,
        center: tuple[float, float],
        radius: float | None = None,
        poi_type: str | list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get Points of Interest (POIs) around a central point based on type.

        - **Args**:
            - `center` (`Tuple[float, float]`): The central point as a tuple.
            - `radius` (`Optional[float]`): The search radius in meters. If not provided, all POIs are considered.
            - `poi_type` (`Optional[Union[str, List[str]]]`): The category or categories of POIs to filter by. Can be first-level categories, second-level categories, or None for all POIs.

        - **Returns**:
            - `List[Dict]`: A list of dictionaries containing information about the POIs found.
        """
        # If no poi_type specified, return all POIs
        if poi_type is None:
            assert self._map is not None
            all_pois: list[tuple[dict, float]] = self._map.query_pois(
                center=center,
                radius=radius,
            )
            pois = [{"poi": poi, "distance": distance} for poi, distance in all_pois]
            return pois[:limit]

        # Process poi_type input
        if isinstance(poi_type, str):
            poi_type = [poi_type]

        transformed_poi_type: list[str] = []
        for t in poi_type:
            if t in self._map.poi_cate:
                # This is a first-level category, expand to all subcategories
                transformed_poi_type += self._map.poi_cate[t]
            else:
                # This is either a second-level category or unknown category
                transformed_poi_type.append(t)

        poi_type_set = set(transformed_poi_type)

        # query pois within the radius
        assert self._map is not None
        nearest_pois: list[tuple[dict, float]] = self._map.query_pois(
            center=center,
            radius=radius,
        )

        # Filter POIs by category
        pois = []
        for poi, distance in nearest_pois:
            catg = poi["category"]
            # Check if any category in the POI matches our filter
            if any(c in poi_type_set for c in catg):
                pois.append({"poi": poi, "distance": distance})

        return pois[:limit]

    # ============================================================================
    # Mobility Management Functions for LLM Function Calling
    # ============================================================================

    @tool(readonly=True, kind="observe")
    async def get_person(self, person_id: int) -> GetPersonResponse:
        """
        Get the current location and status of a person, including position, movement state, and trip progress.

        :param person_id: The ID of the person to query

        :returns: The context containing detailed location and movement information
        """
        if person_id not in self._persons:
            raise ValueError(f"Person {person_id} not found")

        person = self._persons[person_id]

        # Construct target response if target exists
        target_response = None
        if person.target is not None:
            target_response = TargetResponse(
                position=person.target.position,
                mode=person.target.mode,
            )

        # Build nearby POI summary when idle
        nearby_summary = None
        if person.status == "idle" and self._map is not None:
            try:
                from agentsociety2.contrib.env.mobility_space.utils.const import (
                    POI_CATG_DICT,
                )

                pos = person.position
                center = (pos.xy[0], pos.xy[1])
                nearby_summary = []
                for cat_name in POI_CATG_DICT:
                    pois_raw = self._get_around_pois(
                        center=center,
                        radius=3000,
                        poi_type=[cat_name],
                        limit=50,
                    )
                    if pois_raw:
                        nearest = min(pois_raw, key=lambda p: p["distance"])
                        nearby_summary.append(
                            NearbyPoiSummary(
                                category=cat_name,
                                count=len(pois_raw),
                                nearest_name=nearest["poi"].get("name", "unknown"),
                                nearest_distance=round(nearest["distance"], 1),
                            )
                        )
            except Exception:
                nearby_summary = None

        return GetPersonResponse(
            id=person.id,
            status=person.status,
            position=self._person_position_for_response(person),
            target=target_response,
            nearby_pois=nearby_summary,
            work_aoi=person.work_aoi,
            home_aoi=person.home_aoi,
        )

    def mobility_person(self, person_id: int) -> MobilityPerson:
        if person_id not in self._persons:
            raise ValueError(f"Person {person_id} not found")
        return self._persons[person_id]

    def _poi_category_for_id(self, poi_id: int | None) -> str | None:
        if poi_id is None:
            return None
        poi = self._map.get_poi(poi_id)
        if poi is None:
            return None
        category = poi.get("category")
        if isinstance(category, list) and category:
            return str(category[-1])
        if isinstance(category, str) and category:
            return category
        return None

    def _person_position_for_response(self, person: MobilityPerson) -> Position:
        pos = person.position
        if pos.poi_id is None:
            return pos
        category = self._poi_category_for_id(pos.poi_id)
        if category and pos.poi_category != category:
            return pos.model_copy(update={"poi_category": category})
        return pos

    def anchor_idle_position(self, person: MobilityPerson) -> None:
        """Fill aoi/poi on idle positions left on a lane after stop_trip or mid-route."""
        if person.status != "idle":
            return
        pos = person.position
        if pos.aoi_id is not None and pos.kind == "aoi":
            return
        if pos.xy is None:
            return
        x, y = float(pos.xy[0]), float(pos.xy[1])
        pois = self._get_around_pois(center=(x, y), radius=200.0, limit=5)
        if pois:
            hit = min(pois, key=lambda item: item["distance"])
            if float(hit["distance"]) <= 150.0:
                poi = hit["poi"]
                px, py = poi["position"]["x"], poi["position"]["y"]
                person.position = Position(
                    kind="aoi",
                    aoi_id=int(poi["aoi_id"]),
                    poi_id=int(poi["id"]),
                    poi_category=self._poi_category_for_id(int(poi["id"])),
                    xy=(px, py),
                    lnglat=self._map.projector(px, py, inverse=True),
                )
                return
        aois = self._map.query_aois((x, y), radius=800.0, limit=1)
        if aois:
            aoi, _dist = aois[0]
            ax, ay = aoi["shapely_xy"].centroid.x, aoi["shapely_xy"].centroid.y
            person.position = Position(
                kind="aoi",
                aoi_id=int(aoi["id"]),
                poi_id=None,
                xy=(ax, ay),
                lnglat=self._map.projector(ax, ay, inverse=True),
            )

    def _snap_person_to_target_position(self, person: MobilityPerson) -> None:
        if person.target is None:
            get_logger().warning(
                "Person %s: _snap_person_to_target_position called with target=None — resetting to idle",
                person.id,
            )
            person.status = "idle"
            return
        person.status = "idle"
        person.position = person.target.position.model_copy(deep=True)
        person.position.kind = "aoi"
        assert person.position.aoi_id is not None
        if person.position.poi_id is not None:
            poi = self._map.get_poi(person.position.poi_id)
            assert poi is not None
            x, y = poi["position"]["x"], poi["position"]["y"]
            person.position.xy = (x, y)
            person.position.lnglat = self._map.projector(x, y, inverse=True)
            category = self._poi_category_for_id(person.position.poi_id)
            if category:
                person.position.poi_category = category
        else:
            aoi = self._map.get_aoi(person.position.aoi_id)
            assert aoi is not None
            x, y = aoi["shapely_xy"].centroid.x, aoi["shapely_xy"].centroid.y
            person.position.xy = (x, y)
            person.position.lnglat = self._map.projector(x, y, inverse=True)
        person.target = None

    async def stop_trip(self, person_id: int) -> dict:
        if person_id not in self._persons:
            raise ValueError(f"Person {person_id} not found")
        person = self._persons[person_id]
        if person.status != "moving" or person.target is None:
            return {"status": "ok", "was_moving": False}
        xy = person.target.path.interpolate(person.target.path_s)
        person.position.xy = (xy.x, xy.y)
        person.position.lnglat = self._map.projector(xy.x, xy.y, inverse=True)
        person.status = "idle"
        person.target = None
        self.anchor_idle_position(person)
        return {"status": "ok", "was_moving": True}

    async def finish_trip(self, person_id: int) -> dict:
        if person_id not in self._persons:
            raise ValueError(f"Person {person_id} not found")
        person = self._persons[person_id]
        if person.status != "moving" or person.target is None:
            return {"status": "ok", "was_moving": False}
        self._snap_person_to_target_position(person)
        return {"status": "ok", "was_moving": True, "finished": True}

    @tool(readonly=False)
    async def move_to(
        self,
        person_id: int,
        aoi_id_or_poi_id: int,
        mode: Literal["walking", "driving"] = "driving",
    ):
        """
        Plan and start a trip for a person to move to a specific AOI or POI.

        :param person_id: The ID of the person to move
        :param aoi_id_or_poi_id: The target location ID (AOI ID or POI ID starting from 700000000)
        :param mode: The travel mode (walking or driving)

        :returns: Dict with status and details
        """
        if person_id not in self._persons:
            raise ValueError(f"Person {person_id} not found")

        person = self._persons[person_id]

        if person.status == "moving":
            return {"status": "fail", "reason": f"Person {person_id} is already moving"}

        # 1. choose mode

        # choose the start position
        if person.position.kind == "aoi":
            start_position = {
                "aoi_position": {
                    "aoi_id": person.position.aoi_id,
                }
            }
        else:
            # search for nearest road
            radius = 1000
            lanes = []
            while radius < 10000:
                lanes = self._map.query_lane(
                    person.position.xy, radius, 1 if mode == "driving" else 2
                )
                if len(lanes) > 0:
                    break
                radius *= 2
            if len(lanes) == 0:
                return {
                    "status": "fail",
                    "reason": f"No road found near position {person.position.xy} within 10km for mode {mode}",
                }
            lane, s, _ = lanes[0]
            start_position = {
                "lane_position": {
                    "lane_id": lane["id"],
                    "s": s,
                }
            }

        # Get destination position
        if aoi_id_or_poi_id >= POI_START_ID:
            poi = self._map.get_poi(aoi_id_or_poi_id)
            if poi is None:
                return {
                    "status": "fail",
                    "reason": f"POI {aoi_id_or_poi_id} not found",
                }
            destination_position = {
                "aoi_position": {
                    "aoi_id": poi["aoi_id"],
                }
            }
        else:
            aoi = self._map.get_aoi(aoi_id_or_poi_id)
            if aoi is None:
                return {
                    "status": "fail",
                    "reason": f"AOI {aoi_id_or_poi_id} not found",
                }
            destination_position = {
                "aoi_position": {
                    "aoi_id": aoi_id_or_poi_id,
                }
            }

        # Call routing service to get route
        url = f"http://{self._server_addr}/city.routing.v2.RoutingService/GetRoute"
        request_data = {
            "type": (
                TripMode.TRIP_MODE_DRIVE_ONLY
                if mode == "driving"
                else TripMode.TRIP_MODE_WALK_ONLY
            ),
            "start": start_position,
            "end": destination_position,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=request_data) as response:
                    if response.status != 200:
                        return {
                            "status": "fail",
                            "reason": f"Routing service returned status {response.status}",
                        }
                    response_data = await response.json()
        except Exception as e:
            return {
                "status": "fail",
                "reason": f"Routing service error: {e}",
            }
        eta = self._map.estimate_route_time(request_data, response_data)
        try:
            xys = self._map._route_to_xys(request_data, response_data)
        except (IndexError, ValueError) as e:
            return {
                "status": "fail",
                "reason": f"Could not build route geometry: {e}",
            }
        if xys.shape[0] < 2:
            return {
                "status": "fail",
                "reason": "Route geometry has fewer than 2 points",
            }
        path = LineString(xys)
        if path.length <= 0:
            return {"status": "fail", "reason": "Route path length is zero"}
        path_v = path.length / eta if eta > 0 else 1.0
        if path.length > 0:
            min_path_v = path.length / BENCHMARK_SLOT_TICK_SEC
            path_v = max(path_v, min_path_v)

        # Determine destination position with poi_id if applicable
        dest_aoi_id = destination_position["aoi_position"]["aoi_id"]
        dest_poi_id = aoi_id_or_poi_id if aoi_id_or_poi_id >= POI_START_ID else None
        if dest_poi_id is not None:
            # Use POI position
            poi = self._map.get_poi(dest_poi_id)
            if poi is None:
                return {
                    "status": "fail",
                    "reason": f"POI {dest_poi_id} not found",
                }
            x, y = poi["position"]["x"], poi["position"]["y"]
            poi_xy = (x, y)
            poi_lnglat = self._map.projector(poi_xy[0], poi_xy[1], inverse=True)
            target_position = Position(
                kind="aoi",
                aoi_id=dest_aoi_id,
                poi_id=dest_poi_id,
                xy=poi_xy,
                lnglat=poi_lnglat,
            )
        else:
            # Use route end position (AOI centroid)
            target_position = Position(
                kind="aoi",
                aoi_id=dest_aoi_id,
                poi_id=None,
                xy=xys[-1],
                lnglat=self._map.projector(xys[-1][0], xys[-1][1], inverse=True),
            )

        person.target = Target(
            position=target_position,
            mode=mode,
            path=path,
            path_s=0.0,
            path_v=path_v,
        )
        # Update person state ONLY after target is set
        person.status = "moving"
        xy = path.interpolate(0)
        person.position = Position(
            kind="lane",
            aoi_id=None,
            poi_id=None,
            xy=(xy.x, xy.y),
            lnglat=self._map.projector(xy.x, xy.y, inverse=True),
        )

        return {
            "status": "success",
            "person_id": person_id,
            "destination_id": aoi_id_or_poi_id,
            "mode": mode,
            "eta": eta,
        }

    @tool(readonly=True)
    async def find_nearby_pois(
        self, x: float, y: float, category: str | None, radius: float
    ) -> FindNearbyPoisResponse:
        """
        Discover Points of Interest (POIs) near a location, filtered by category and distance.

        :param x: The longitude (x coordinate) of the search center
        :param y: The latitude (y coordinate) of the search center
        :param category: POI category filter - first-level (e.g., 'restaurant'), second-level (e.g., 'cafe'), or None for all categories. Available first-level categories (with examples): - 'children_playground': playground, summer_camp, miniature_golf, dog_park - 'cultural_and_artistic': arts_centre, brothel, casino, cinema, community_centre - 'education_institution': college, dancing_school, driving_school, first_aid_school, kindergarten - 'financial_service': atm, payment_terminal, bank, bureau_de_change, money_transfer - 'indoor_entertainment': adult_gaming_centre, amusement_arcade, bowling_alley, disc_golf_course, escape_game - 'medical_care': baby_hatch, clinic, dentist, doctors, hospital - 'nature_and_wildlife_observation': bird_hide, nature_reserve, wildlife_hide, hunting_stand - 'other_special_purpose': animal_boarding, animal_breeding, animal_shelter, animal_training, baking_oven - 'outdoor_activity': bandstand, beach_resort, bird_hide, bleachers, firepit - 'public_service': bbq, bench, dog_toilet, dressing_room, drinking_water - 'restaurant': bar, biergarten, cafe, fast_food, food_court - 'sports_facility': horse_riding, ice_rink, marina, pitch, sports_centre - 'transportation_facility': bicycle_parking, bicycle_repair_station, bicycle_rental, bicycle_wash, boat_rental - 'water_activity': beach_resort, ice_rink, marina, slipway, swimming_area You can also use any first-level category or second-level category directly (e.g., 'children_playground' 'cafe', 'park', 'hospital').
        :param radius: Search radius in meters (e.g., 1000 for 1km)

        :returns: Structured data containing POI list with IDs, names, categories, positions, and distances
        """
        pois = self._get_around_pois(
            center=(x, y),
            radius=radius,
            poi_type=category,
            limit=self._poi_search_limit,
        )
        clean_pois = []
        for p in pois:
            clean_poi = Poi(
                id=p["poi"]["id"],
                name=p["poi"]["name"],
                position=p["poi"]["position"],
                category=p["poi"]["category"][-1],
                aoi_id=self.poi_id_2_aoi_id.get(p["poi"]["id"]),
                distance=p["distance"],
            )
            clean_pois.append(clean_poi)

        return FindNearbyPoisResponse(pois=clean_pois)

    @tool(readonly=True)
    async def get_poi(self, poi_id: int) -> Poi:
        """
        Retrieve detailed information about a specific Point of Interest.

        :param poi_id: The unique ID of the POI (starts from 700000000)

        :returns: Structured data containing POI details (ID, name, category, position)
        """
        poi = self._map.get_poi(poi_id)
        if poi is None:
            raise ValueError(f"POI {poi_id} not found")

        poi_obj = Poi(
            id=poi["id"],
            name=poi["name"],
            category=poi["category"][-1],
            position=poi["position"],
            aoi_id=poi.get("aoi_id"),
            distance=None,
        )

        return poi_obj

    @tool(readonly=True)
    async def recommend_poi_by_gravity(
        self,
        person_id: int,
        category: str | None = None,
        radius: float = 1200,
        exclude_home_work: bool = True,
    ) -> dict:
        """Recommend a nearby POI using a gravity model that balances distance and density.

        The gravity model prefers POIs that are closer and located in areas with
        higher density of similar POIs, producing a natural spatial distribution.

        :param person_id: The ID of the person to find a POI for
        :param category: POI category filter (e.g. 'restaurant'); None for all
        :param radius: Search radius in meters (default 1200)
        :param exclude_home_work: Exclude POIs at the person's home/work AOI
        :returns: Dict with recommended POI details and suggested travel mode
        """
        if person_id not in self._persons:
            raise ValueError(f"Person {person_id} not found")

        from agentsociety2.contrib.env.mobility_space.utils.poi_gravity import (
            filter_out_of_anchor_aoi_pois,
            gravity_model,
            poi_travel_mode,
        )

        person = self._persons[person_id]
        center = person.position.xy

        raw_pois = self._get_around_pois(
            center=center,
            radius=radius,
            poi_type=category,
            limit=self._poi_search_limit,
        )

        # Normalize to standard dicts with distance
        candidates: list[dict] = []
        for item in raw_pois:
            poi = item["poi"]
            dist = item["distance"]
            candidates.append(
                {
                    "poi_id": poi["id"],
                    "name": poi["name"],
                    "category": poi["category"][-1]
                    if isinstance(poi["category"], list) and poi["category"]
                    else str(poi.get("category", "")),
                    "distance": dist,
                    "aoi_id": poi.get("aoi_id") or self.poi_id_2_aoi_id.get(poi["id"]),
                }
            )

        if not candidates:
            return {"status": "no_candidates", "reason": "No POIs found in search area"}

        if exclude_home_work:
            candidates = filter_out_of_anchor_aoi_pois(
                candidates,
                home_aoi=person.home_aoi,
                work_aoi=person.work_aoi,
            )

        if not candidates:
            return {
                "status": "no_candidates",
                "reason": "All POIs filtered by home/work exclusion",
            }

        selected = gravity_model(candidates)
        if selected is None:
            return {
                "status": "no_candidates",
                "reason": "Gravity model returned no result",
            }

        distance = float(selected.get("distance", 0))
        mode = poi_travel_mode(distance)

        return {
            "status": "success",
            "poi_id": selected["poi_id"],
            "name": selected.get("name", "unknown"),
            "category": selected.get("category", ""),
            "distance": distance,
            "aoi_id": selected.get("aoi_id"),
            "recommended_mode": mode,
        }

    async def close(self):
        """Terminate the simulation process and export trajectory data."""
        self._export_trajectory_data()
        if self._routing_proc is not None and self._routing_proc.poll() is None:
            get_logger().info(
                f"Terminating routing at {self._server_addr}, PID={self._routing_proc.pid}, please ignore the PANIC message"
            )
            self._routing_proc.kill()
            self._routing_proc.wait()
        self._routing_proc = None

    def _export_trajectory_data(self) -> None:
        """Export trajectories and visited AOIs to run directory."""
        if not self._home_dir:
            return
        export_path = Path(self._home_dir).parent / "mobility_metrics_export.json"
        trajs = self.get_all_persons_trajectories()
        vis = self.get_all_persons_visited_aois()
        if not trajs:
            return
        data = {
            "trajectories": {str(k): v for k, v in trajs.items()},
            "visited_aois": {str(k): sorted(v) for k, v in vis.items()},
        }
        export_path.write_text(json.dumps(data), encoding="utf-8")
        get_logger().info(
            f"Exported mobility data to {export_path} ({len(trajs)} agents)"
        )

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks (1 tick = 1 second) of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        # Update all moving persons
        for person in self._persons.values():
            if person.status == "moving":
                if person.target is None:
                    get_logger().warning(
                        "Person %s: status=moving but target is None — resetting to idle",
                        person.id,
                    )
                    person.status = "idle"
                    self.anchor_idle_position(person)
                    continue
                distance_to_move = person.target.path_v * tick
                person.target.path_s += distance_to_move
                if person.target.path_s >= person.target.path.length:
                    self._snap_person_to_target_position(person)
                else:
                    # update position
                    xy = person.target.path.interpolate(person.target.path_s)
                    person.position.xy = (xy.x, xy.y)
                    person.position.lnglat = self._map.projector(
                        xy.x, xy.y, inverse=True
                    )

            # 【关键】每步记录person的位置（用于轨迹收集）
            self.record_person_position(person.id)

            # Write position to replay database
            lng, lat = person.position.lnglat
            await self._write_agent_state(
                agent_id=person.id,
                step=self._step_counter,
                t=t,
                lng=lng,
                lat=lat,
                aoi_id=person.position.aoi_id,
                poi_id=person.position.poi_id,
                status=person.status,
            )

        self.t = t
        self._step_counter += 1

    # ==================== workspace 持久化（无状态 resume） ====================
    #
    # 本模块自选布局：<workspace_root>/state/ENV_STATE.json。持久化动态状态
    # （persons 位置、轨迹、已访问 AOI、step 计数）；``_map`` / routing server
    # 属静态/可重建（由 ``__init__`` 从 file_path 重建 map、由 ``init()`` 重启
    # routing 进程），不存盘。

    _STATE_REL = "state/ENV_STATE.json"

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json``（原子写）。

        pydantic ``MobilityPerson`` 用 model_dump；轨迹 tuple → list、visited
        AOI set → list 以便 JSON；``_map`` 与 routing 进程不存盘（可重建）。
        """
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / self._STATE_REL,
            json.dumps(
                {
                    "persons": {
                        str(pid): p.model_dump(mode="json")
                        for pid, p in self._persons.items()
                    },
                    "person_trajectories": dump_int_map(
                        {
                            pid: [list(xy) for xy in traj]
                            for pid, traj in self._person_trajectories.items()
                        }
                    ),
                    "person_visited_aois": dump_int_map(
                        {
                            pid: sorted(aois)
                            for pid, aois in self._person_visited_aois.items()
                        }
                    ),
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。

        晚于 ``__init__``（重建 map）与 ``init()``（重启 routing）执行，覆盖
        persons / 轨迹 / 已访问 AOI / step 计数。
        """
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / self._STATE_REL
        if not state_path.is_file():
            return False
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self._persons = {
            pid: MobilityPerson.model_validate(p)
            for pid, p in load_int_map(state.get("persons")).items()
        }
        self._person_trajectories = {
            pid: [tuple(xy) for xy in traj]
            for pid, traj in load_int_map(state.get("person_trajectories")).items()
        }
        self._person_visited_aois = {
            pid: set(aois)
            for pid, aois in load_int_map(state.get("person_visited_aois")).items()
        }
        self._step_counter = int(state.get("step_counter", 0))
        return True

    # ==================== Replay Data Methods ====================
