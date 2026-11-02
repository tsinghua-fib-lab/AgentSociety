"""Event Space: Event Management and Tracking Module

Supports 7 specific event types:
- sleep: Sleeping/rest periods
- home activity: Activities at home (e.g., cooking, cleaning, household chores)
- work: Work-related activities and tasks
- shopping: Shopping or purchasing activities
- eating out: Eating at restaurants or food establishments
- leisure and entertainment: Leisure, entertainment, social activities
- other: Any other activities not covered above
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.env.base import dump_int_map, load_int_map
from agentsociety2.logger import get_logger
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"

# Valid event types for person behavior tracking
VALID_EVENT_TYPES = Literal[
    "sleep",
    "home activity",
    "other",
    "work",
    "shopping",
    "eating out",
    "leisure and entertainment",
]

DEFAULT_ALLOWED_EVENT_TYPES = [
    "sleep",
    "home activity",
    "other",
    "work",
    "shopping",
    "eating out",
    "leisure and entertainment",
]

# Event types configuration string - easily modifiable for future changes
# This string is used in description to show available event commands to the LLM
DEFAULT_EVENT_TYPES_CONFIG = """
**Sleep Events**: start_event(person_id, "sleep", event_name, duration_seconds)
  - Examples: "night sleep", "afternoon nap"
  - You should not do other activities during sleep. Unless you wake up unexpectedly.

**Home Activity Events**: start_event(person_id, "home activity", event_name, duration_seconds)
  - Examples: "cooking dinner", "cleaning house", "laundry"

**Work Events**: start_event(person_id, "work", event_name, duration_seconds)
  - Examples: "team meeting", "coding task", "email work"

**Shopping Events**: start_event(person_id, "shopping", event_name, duration_seconds)
  - Examples: "grocery shopping", "clothes shopping"

**Eating Out Events**: start_event(person_id, "eating out", event_name, duration_seconds)
  - Examples: "lunch at restaurant", "dinner with friends"

**Leisure and Entertainment Events**: start_event(person_id, "leisure and entertainment", event_name, duration_seconds)
  - Examples: "watching movie", "playing game", "socializing"

**Other Events**: start_event(person_id, "other", event_name, duration_seconds)
  - For any activities not covered by the above categories
"""

__all__ = [
    "VALID_EVENT_TYPES",
    "CurrentEvent",
    "EndEventResponse",
    "EventSpace",
    "GetEventResponse",
    "StartEventResponse",
]


class CurrentEvent(BaseModel):
    """Represents a person's current behavior event"""

    person_id: int = Field(..., description="Person ID")
    event_type: str = Field(
        ...,
        description="Type of event",
    )
    event_name: str = Field(
        ...,
        description="Name/description of the event (e.g., 'afternoon nap', 'meeting with team')",
    )
    status: Literal["in_progress", "completed", "cancelled"] = Field(
        default="in_progress", description="Current status of the event"
    )
    start_time: datetime = Field(..., description="Event start time")
    expected_end_time: datetime | None = Field(
        default=None, description="Expected end time provided by person"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def type(self) -> str:
        """Alias for event_type to support both .type and .event_type access"""
        return self.event_type

    @property
    def name(self) -> str:
        """Alias for event_name to support both .name and .event_name access"""
        return self.event_name

    def get_elapsed_seconds(self, current_time: datetime) -> float:
        """Get elapsed time in seconds"""
        return (current_time - self.start_time).total_seconds()

    def get_remaining_seconds(self, current_time: datetime) -> float | None:
        """Get remaining time in seconds until expected end time (if set)"""
        if self.expected_end_time is None or self.status != "in_progress":
            return None
        remaining = self.expected_end_time - current_time
        return max(0, remaining.total_seconds())

    def get_progress_percentage(self, current_time: datetime) -> float | None:
        """Get progress percentage (0-100) based on expected end time"""
        if self.expected_end_time is None:
            return None
        total_duration = (self.expected_end_time - self.start_time).total_seconds()
        if total_duration <= 0:
            return 0
        elapsed = self.get_elapsed_seconds(current_time)
        return min(100, (elapsed / total_duration) * 100)


# Response models for tool functions
class StartEventResponse(BaseModel):
    """Response model for start_event() function"""

    person_id: int = Field(..., description="Person ID")
    event_type: str = Field(..., description="Type of event")
    event_name: str = Field(..., description="Event name/description")
    start_time: datetime = Field(..., description="Event start time")
    expected_end_time: datetime = Field(..., description="Expected end time")
    status: str = Field(..., description="Event status")

    @property
    def type(self) -> str:
        """Alias for event_type to support both .type and .event_type access"""
        return self.event_type

    @property
    def name(self) -> str:
        """Alias for event_name to support both .name and .event_name access"""
        return self.event_name


class GetEventResponse(BaseModel):
    """Response model for get_event() function"""

    person_id: int = Field(..., description="Person ID")
    event_type: str = Field(..., description="Type of event")
    event_name: str = Field(..., description="Event name/description")
    status: str = Field(..., description="Event status")
    start_time: datetime = Field(..., description="Start time")
    expected_end_time: datetime | None = Field(None, description="Expected end time")
    elapsed_seconds: float = Field(..., description="Elapsed time in seconds")
    remaining_seconds: float | None = Field(
        None, description="Remaining time in seconds (if expected_end_time set)"
    )
    progress_percentage: float | None = Field(
        None, description="Progress percentage (0-100, if expected_end_time set)"
    )

    @property
    def type(self) -> str:
        """Alias for event_type to support both .type and .event_type access"""
        return self.event_type

    @property
    def name(self) -> str:
        """Alias for event_name to support both .name and .event_name access"""
        return self.event_name


class EndEventResponse(BaseModel):
    """Response model for end_event() function"""

    success: bool = Field(..., description="Whether update was successful")
    message: str = Field(..., description="Status message")


class EventSpace(EnvBase):
    """
    Event Space: A module for managing and tracking person's current behavior event.

    Each person maintains at most one active event at a time.

    Features:
    - Start an event for a person with expected duration
    - Track event progress and duration
    - Query event status and metrics
    - End/cancel events with timestamps
    """

    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("active_event_count", "INTEGER", nullable=False),
        ColumnDef("active_events", "JSON", nullable=False),
        ColumnDef("allowed_event_types", "JSON", nullable=False),
        ColumnDef("event_types_description", "TEXT", nullable=False),
    ]

    def __init__(
        self,
        allowed_event_types: list[str] = DEFAULT_ALLOWED_EVENT_TYPES,
        event_types_description: str = DEFAULT_EVENT_TYPES_CONFIG,
    ):
        """Initialize the EventSpace"""
        super().__init__()
        self._allowed_event_types = allowed_event_types
        self._event_types_description = event_types_description
        self._agent_events: dict[int, CurrentEvent] = {}
        """Storage for current event of each person: person_id -> CurrentEvent"""
        self._recent_stopped_events: dict[int, CurrentEvent] = {}
        """Last event stopped at the current env clock, used to absorb same-tick restarts."""
        self._step_counter: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。CurrentEvent(pydantic) 用 model_dump。"""
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "agent_events": {
                        k: e.model_dump(mode="json")
                        for k, e in dump_int_map(self._agent_events).items()
                    },
                    "recent_stopped_events": {
                        k: e.model_dump(mode="json")
                        for k, e in dump_int_map(self._recent_stopped_events).items()
                    },
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。"""
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        d = json.loads(state_path.read_text(encoding="utf-8"))
        self._agent_events = {
            pid: CurrentEvent.model_validate(e)
            for pid, e in load_int_map(d.get("agent_events")).items()
        }
        self._recent_stopped_events = {
            pid: CurrentEvent.model_validate(e)
            for pid, e in load_int_map(d.get("recent_stopped_events")).items()
        }
        self._step_counter = int(d.get("step_counter", 0))
        return True

    # ---- Skill Discovery ----

    @classmethod
    def skill_dirs(cls) -> list[Path]:
        skills_dir = Path(__file__).parent / "agent_skills"
        return [skills_dir] if skills_dir.is_dir() else []

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return (
            "Event tracking environment for recording and querying person activities."
        )

    async def init(self, start_datetime: datetime) -> Any:
        """
        Initialize the EventSpace.

        :param start_datetime: The simulation start time
        """
        await super().init(start_datetime)
        self._agent_events.clear()
        self._recent_stopped_events.clear()
        self._step_counter = 0
        get_logger().info("EventSpace initialized")

    def _serialize_active_events(
        self, current_time: datetime
    ) -> dict[str, dict[str, Any]]:
        """Serialize active events to JSON-safe dictionaries for replay output."""
        result: dict[str, dict[str, Any]] = {}
        for person_id, event in self._agent_events.items():
            result[str(person_id)] = {
                **event.model_dump(mode="json"),
                "elapsed_seconds": event.get_elapsed_seconds(current_time),
                "remaining_seconds": event.get_remaining_seconds(current_time),
                "progress_percentage": event.get_progress_percentage(current_time),
            }
        return result

    def _create_and_start_event(
        self,
        person_id: int,
        event_type: str,
        event_name: str,
        expected_duration_seconds: float,
    ) -> StartEventResponse:
        """
        Internal helper to create and start an event.

        :param person_id: The ID of the person
        :param event_type: Type of event
        :param event_name: Name or description of the event
        :param expected_duration_seconds: Expected duration in seconds

        :returns: Response containing the started event information
        """
        start_time = self.t

        # Check if duration is provided and valid
        if expected_duration_seconds is None or expected_duration_seconds <= 0:
            raise ValueError(
                "expected_duration_seconds is required and must be positive. "
                "Please specify how long the event should take in seconds. "
                "Examples: 3600 for 1 hour, 28800 for 8 hours, 1800 for 30 minutes."
            )
        expected_duration_seconds = self._normalize_event_duration_seconds(
            event_type,
            expected_duration_seconds,
        )

        # Calculate expected end time
        expected_end = start_time + timedelta(seconds=expected_duration_seconds)

        active = self._agent_events.get(person_id)
        if active is not None:
            if active.event_type == event_type:
                get_logger().info(
                    "Event start absorbed by active event: person_id=%s, event_type=%s, event_name=%s, end_time=%s",
                    person_id,
                    event_type,
                    active.event_name,
                    active.expected_end_time.isoformat()
                    if active.expected_end_time is not None
                    else None,
                )
                return StartEventResponse(
                    person_id=person_id,
                    event_type=active.event_type,
                    event_name=active.event_name,
                    start_time=active.start_time,
                    expected_end_time=active.expected_end_time or expected_end,
                    status="in_progress",
                )
            raise ValueError(
                f"Event {active.event_type}/{active.event_name} already exists for person {person_id}. "
                "Please stop the existing event first."
            )

        recent = self._recent_stopped_events.get(person_id)
        if recent is not None and self._is_passive_placeholder_event(
            event_type,
            event_name,
        ):
            recent.status = "in_progress"
            self._agent_events[person_id] = recent
            del self._recent_stopped_events[person_id]
            get_logger().info(
                "Passive placeholder event ignored: person_id=%s, requested_type=%s, requested_name=%s, restored_type=%s",
                person_id,
                event_type,
                event_name,
                recent.event_type,
            )
            return StartEventResponse(
                person_id=person_id,
                event_type=recent.event_type,
                event_name=recent.event_name,
                start_time=recent.start_time,
                expected_end_time=recent.expected_end_time or expected_end,
                status="in_progress",
            )
        if recent is not None and recent.event_type == event_type:
            recent.status = "in_progress"
            if recent.expected_end_time is None:
                recent.expected_end_time = expected_end
            self._agent_events[person_id] = recent
            del self._recent_stopped_events[person_id]
            get_logger().info(
                "Event restart absorbed: person_id=%s, event_type=%s, event_name=%s, end_time=%s",
                person_id,
                event_type,
                recent.event_name,
                recent.expected_end_time.isoformat()
                if recent.expected_end_time is not None
                else None,
            )
            return StartEventResponse(
                person_id=person_id,
                event_type=recent.event_type,
                event_name=recent.event_name,
                start_time=recent.start_time,
                expected_end_time=recent.expected_end_time or expected_end,
                status="in_progress",
            )

        # Create new event
        event = CurrentEvent(
            person_id=person_id,
            event_type=event_type,
            event_name=event_name,
            status="in_progress",
            start_time=start_time,
            expected_end_time=expected_end,
        )

        self._agent_events[person_id] = event

        get_logger().info(
            f"Event started: person_id={person_id}, event_type={event_type}, event_name={event_name}, duration={expected_duration_seconds}s, end_time={expected_end.isoformat()}"
        )

        return StartEventResponse(
            person_id=person_id,
            event_type=event_type,
            event_name=event_name,
            start_time=start_time,
            expected_end_time=expected_end,
            status="in_progress",
        )

    @tool(readonly=False)
    async def start_event(
        self,
        person_id: int,
        event_type: str,
        event_name: str,
        expected_duration_seconds: float,
    ) -> StartEventResponse:
        """
        Start an event for a person.

        :param person_id: The ID of the person
        :param event_type: Type of event - one of: sleep, home activity, work, shopping, eating out, leisure and entertainment, other
        :param event_name: Description or name of the specific activity
        :param expected_duration_seconds: Expected duration in seconds (e.g., 3600 for 1 hour, 28800 for 8 hours, 1800 for 30 minutes)

        :returns: Response containing the started event information
        """
        # Validate event_type
        if event_type not in self._allowed_event_types:
            raise ValueError(
                f"Invalid event_type: {event_type}. Must be one of: {', '.join(self._allowed_event_types)}"
            )

        return self._create_and_start_event(
            person_id=person_id,
            event_type=event_type,  # type: ignore
            event_name=event_name,
            expected_duration_seconds=expected_duration_seconds,
        )

    @staticmethod
    def _normalize_event_duration_seconds(
        event_type: str,
        expected_duration_seconds: float,
    ) -> float:
        """归一化事件时长中常见的单位错误。

        :param event_type: 事件类别。
        :param expected_duration_seconds: 传给 start_event 的原始时长。
        :returns: 秒为单位的时长。
        """
        duration = float(expected_duration_seconds)
        if event_type == "sleep":
            if 0 < duration <= 12:
                return duration * 3600
            if 12 < duration <= 720:
                return duration * 60
        return duration

    @staticmethod
    def _is_passive_placeholder_event(event_type: str, event_name: str) -> bool:
        """判断请求的事件是否只是被动等待/检查。

        :param event_type: 请求的事件类型。
        :param event_name: 请求的事件名称。
        :returns: 该请求不应替代真实主动活动时为 True。
        """
        value = f"{event_type} {event_name}".lower()
        passive_terms = (
            "wait",
            "waiting",
            "observe",
            "observation",
            "check",
            "status",
            "monitor",
            "continue",
        )
        return any(term in value for term in passive_terms)

    @tool(readonly=True, kind="observe")
    async def get_current_event(self, person_id: int) -> GetEventResponse | None:
        """
        Query current event information for a person.

        :param person_id: The ID of the person

        :returns: Response containing event details including type, status, timestamps, duration, and progress, or None if no active event
        """
        if person_id not in self._agent_events:
            return None

        event = self._agent_events[person_id]

        # Only return active events, not completed or cancelled ones
        if event.status != "in_progress":
            return None

        elapsed = event.get_elapsed_seconds(self.t)
        remaining = event.get_remaining_seconds(self.t)
        progress = event.get_progress_percentage(self.t)

        return GetEventResponse(
            person_id=event.person_id,
            event_type=event.event_type,
            event_name=event.event_name,
            status=event.status,
            start_time=event.start_time,
            expected_end_time=(
                event.expected_end_time if event.expected_end_time else None
            ),
            elapsed_seconds=elapsed,
            remaining_seconds=remaining,
            progress_percentage=progress,
        )

    @tool(readonly=False)
    async def stop_event(
        self,
        person_id: int,
        status: Literal["completed", "cancelled"] = "completed",
    ) -> EndEventResponse:
        """
        Stop (complete or cancel) the current event for a person.

        :param person_id: The ID of the person
        :param status: Event end status ("completed" or "cancelled")

        :returns: Response indicating success and status message
        """
        if person_id not in self._agent_events:
            return EndEventResponse(
                success=False,
                message=f"No active event for person: {person_id}",
            )

        event = self._agent_events[person_id]
        event.status = status
        self._recent_stopped_events[person_id] = event

        get_logger().info(
            f"Event stopped: person_id={person_id}, event_type={event.event_type}, "
            f"event_name={event.event_name}, status={status}, duration={event.get_elapsed_seconds(self.t):.1f}s"
        )

        # Remove the event from active events after stopping
        del self._agent_events[person_id]

        return EndEventResponse(
            success=True,
            message=f"Event {event.event_name} stopped with status: {status}",
        )

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step (update event timestamps).

        :param tick: The number of ticks (1 tick = 1 second)
        :param t: The current datetime after this step
        """
        self.t = t
        self._recent_stopped_events.clear()
        active_events = self._serialize_active_events(t)
        await self._write_env_state(
            step=self._step_counter,
            t=t,
            active_event_count=len(self._agent_events),
            active_events=active_events,
            allowed_event_types=list(self._allowed_event_types),
            event_types_description=self._event_types_description,
        )
        self._step_counter += 1

    async def close(self):
        """
        Close the EventSpace and perform cleanup.
        """
        get_logger().info(
            f"EventSpace closed. Total persons with events: {len(self._agent_events)}"
        )
