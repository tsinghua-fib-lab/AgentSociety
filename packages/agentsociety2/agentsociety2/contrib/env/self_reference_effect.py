"""
Self-Reference Effect (SRE) Experiment Environment
Environment for Self-Reference Effect experiment based on AgentSociety2
"""

import asyncio
import json
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.env.base import dump_int_map, load_int_map
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"


# Identity types
class IdentityType(str, Enum):
    """Identity types for trait adjectives"""

    SELF = "self"
    FRIEND = "friend"
    OTHER = "other"


# Response models for tool functions
class SubmitEncodingRatingResponse(BaseModel):
    """Response model for submit_encoding_rating() function"""

    agent_id: int = Field(..., description="Agent ID")
    trait: str = Field(..., description="Trait adjective")
    identity: str = Field(..., description="Identity type (self, friend, other)")
    rating: int = Field(..., description="Rating score (1-5)")
    status: str = Field(..., description="Status: 'submitted' or 'encoding_completed'")


class SubmitRecognitionResponse(BaseModel):
    """Response model for submit_recognition() function"""

    agent_id: int = Field(..., description="Agent ID")
    trait: str = Field(..., description="Trait adjective")
    judge_type: str = Field(..., description="Recognition judgment (old/new)")
    is_correct: bool = Field(..., description="Whether the recognition is correct")
    rk_type: str | None = Field(
        None, description="Remember/Know judgment (remember/know)"
    )
    status: str = Field(
        ..., description="Status: 'submitted' or 'recognition_completed'"
    )


class GetEncodingStatusResponse(BaseModel):
    """Response model for get_encoding_status() function"""

    agent_id: int = Field(..., description="Agent ID")
    completed_traits: list[dict[str, Any]] = Field(
        ..., description="List of completed encoding ratings"
    )
    remaining_count: int = Field(..., description="Number of remaining traits to rate")


class GetRecognitionStatusResponse(BaseModel):
    """Response model for get_recognition_status() function"""

    agent_id: int = Field(..., description="Agent ID")
    completed_judgments: list[dict[str, Any]] = Field(
        ..., description="List of completed recognition judgments"
    )
    remaining_count: int = Field(..., description="Number of remaining traits to judge")


class SelfReferenceEffectEnv(EnvBase):
    """Environment for Self-Reference Effect (SRE) experiment based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("encoding_ratings", "JSON", nullable=False),
        ColumnDef("recognition_judgments", "JSON", nullable=False),
        ColumnDef("encoding_completed_count", "INTEGER", nullable=False),
        ColumnDef("recognition_completed_count", "INTEGER", nullable=False),
    ]

    def __init__(
        self,
        agent_ids: list[int],
        encoding_traits: list[dict[str, Any]] | None = None,
        recognition_traits: list[str] | None = None,
    ):
        """
        Initialize the Self-Reference Effect environment.

        :param agent_ids: List of agent IDs participating in the experiment
        :param encoding_traits: List of trait dictionaries for encoding phase Each dict should have: {"trait": str, "identity": str, "valence": int} If None, will use default trait list
        :param recognition_traits: List of trait adjectives for recognition phase If None, will use traits from encoding phase plus new traits
        """
        super().__init__()

        self.agent_ids = agent_ids
        self.num_agents = len(agent_ids)

        # Initialize encoding traits if not provided
        if encoding_traits is None:
            # Default trait list - you can customize this
            self.encoding_traits = self._generate_default_encoding_traits()
        else:
            self.encoding_traits = encoding_traits

        # Initialize recognition traits if not provided
        if recognition_traits is None:
            # Use encoding traits plus some new traits
            self.recognition_traits = [
                t["trait"] for t in self.encoding_traits
            ] + self._generate_new_traits()
        else:
            self.recognition_traits = recognition_traits

        # Store encoding ratings: agent_id -> list of {trait, identity, rating}
        self._encoding_ratings: dict[int, list[dict[str, Any]]] = {
            agent_id: [] for agent_id in agent_ids
        }

        # Store recognition judgments: agent_id -> list of {trait, judge_type, is_correct, rk_type}
        self._recognition_judgments: dict[int, list[dict[str, Any]]] = {
            agent_id: [] for agent_id in agent_ids
        }

        # Track which traits were presented in encoding phase (for correctness checking)
        self._encoding_trait_set = {t["trait"] for t in self.encoding_traits}

        self._lock = asyncio.Lock()
        self._step_counter: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。"""
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "encoding_ratings": dump_int_map(self._encoding_ratings),
                    "recognition_judgments": dump_int_map(self._recognition_judgments),
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
        self._encoding_ratings = {
            aid: list(v) for aid, v in load_int_map(d.get("encoding_ratings")).items()
        }
        self._recognition_judgments = {
            aid: list(v)
            for aid, v in load_int_map(d.get("recognition_judgments")).items()
        }
        self._step_counter = int(d.get("step_counter", 0))
        return True

    def _generate_default_encoding_traits(self) -> list[dict[str, Any]]:
        """Generate default trait list for encoding phase"""
        # This is a simplified version - you should load from actual SRE data
        traits = [
            {"trait": "谦和", "identity": "self", "valence": 1},
            {"trait": "善良", "identity": "self", "valence": 1},
            {"trait": "积极", "identity": "friend", "valence": 1},
            {"trait": "整洁", "identity": "other", "valence": 1},
            {"trait": "坦诚", "identity": "other", "valence": 1},
            {"trait": "放荡", "identity": "self", "valence": 2},
            {"trait": "负心", "identity": "other", "valence": 2},
            {"trait": "恶念", "identity": "other", "valence": 2},
            {"trait": "努力", "identity": "other", "valence": 1},
        ]
        return traits

    def _generate_new_traits(self) -> list[str]:
        """Generate new traits for recognition phase (not in encoding)"""
        return ["聪明", "勇敢", "懒惰", "自私"]

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions and JSON schemas for data models.
        """
        description = f"""{cls.__name__}: Self-Reference Effect experiment environment module.

**Description:** Manages a Self-Reference Effect experiment where agents rate trait adjectives in encoding phase and recognize them in recognition phase.

**Initialization Parameters (excluding llm):**
- agent_ids (List[int]): List of agent IDs participating in the experiment
- encoding_traits (List[Dict], optional): List of trait dictionaries for encoding phase
- recognition_traits (List[str], optional): List of trait adjectives for recognition phase

**Example initialization config:**
```json
{{
  "agent_ids": [101, 102, 103]
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Self-Reference Effect experiment environment for encoding and recognition memory tasks."

    @tool(readonly=False)
    async def submit_encoding_rating(
        self, agent_id: int, trait: str, identity: str, rating: int
    ) -> SubmitEncodingRatingResponse:
        """
        Submit rating for a trait adjective in encoding phase.

        :param agent_id: The agent's ID
        :param trait: The trait adjective
        :param identity: Identity type ("self", "friend", or "other")
        :param rating: Rating score (1-5, integer)

        :returns: Response containing submission status.
        """
        async with self._lock:
            # Validate agent_id
            if agent_id not in self.agent_ids:
                raise ValueError(f"Agent ID {agent_id} is not in the experiment")

            # Validate identity
            identity_lower = identity.lower()
            if identity_lower not in ["self", "friend", "other"]:
                raise ValueError(
                    f"Invalid identity: {identity}. Must be one of: self, friend, other"
                )

            # Validate rating
            if not isinstance(rating, int):
                raise ValueError(
                    f"Rating must be an integer, got {type(rating).__name__}"
                )
            rating = max(1, min(5, rating))  # Clamp to 1-5

            # Check if this trait-identity combination exists in encoding traits
            trait_found = False
            for encoding_trait in self.encoding_traits:
                if (
                    encoding_trait["trait"] == trait
                    and encoding_trait["identity"] == identity_lower
                ):
                    trait_found = True
                    break

            if not trait_found:
                raise ValueError(
                    f"Trait '{trait}' with identity '{identity_lower}' not found in encoding traits list"
                )

            # Check if already submitted
            for existing in self._encoding_ratings[agent_id]:
                if (
                    existing["trait"] == trait
                    and existing["identity"] == identity_lower
                ):
                    raise ValueError(
                        f"Rating for trait '{trait}' with identity '{identity_lower}' has already been submitted. "
                        f"Current rating: {existing['rating']}"
                    )

            # Store the rating
            rating_data = {
                "trait": trait,
                "identity": identity_lower,
                "rating": rating,
            }
            self._encoding_ratings[agent_id].append(rating_data)

            # Check if all encoding traits are completed
            completed = len(self._encoding_ratings[agent_id])
            all_completed = completed == len(self.encoding_traits)

            status = "encoding_completed" if all_completed else "submitted"

            # Debug log
            import sys

            print(
                f"[ENV DEBUG] Agent {agent_id} submitted encoding rating: {trait} ({identity_lower}) = {rating} "
                f"({completed}/{len(self.encoding_traits)} completed)",
                file=sys.stderr,
            )

            return SubmitEncodingRatingResponse(
                agent_id=agent_id,
                trait=trait,
                identity=identity_lower,
                rating=rating,
                status=status,
            )

    @tool(readonly=True)
    async def get_encoding_status(self, agent_id: int) -> GetEncodingStatusResponse:
        """
        Get encoding phase status for a specific agent.

        :param agent_id: The agent's ID

        :returns: Response containing completed traits and remaining count.
        """
        async with self._lock:
            if agent_id not in self.agent_ids:
                raise ValueError(f"Agent ID {agent_id} is not in the experiment")

            completed_traits = self._encoding_ratings[agent_id].copy()
            remaining_count = len(self.encoding_traits) - len(completed_traits)

            return GetEncodingStatusResponse(
                agent_id=agent_id,
                completed_traits=completed_traits,
                remaining_count=remaining_count,
            )

    @tool(readonly=False)
    async def submit_recognition(
        self, agent_id: int, trait: str, judge_type: str, rk_type: str | None = None
    ) -> SubmitRecognitionResponse:
        """
        Submit recognition judgment for a trait adjective.

        :param agent_id: The agent's ID
        :param trait: The trait adjective
        :param judge_type: Recognition judgment ("old" or "new")
        :param rk_type: Remember/Know judgment ("remember" or "know", required if judge_type is "old")

        :returns: Response containing judgment status and correctness.
        """
        async with self._lock:
            # Validate agent_id
            if agent_id not in self.agent_ids:
                raise ValueError(f"Agent ID {agent_id} is not in the experiment")

            # Validate judge_type
            judge_type_lower = judge_type.lower()
            if judge_type_lower not in ["old", "new"]:
                raise ValueError(
                    f"Invalid judge_type: {judge_type}. Must be 'old' or 'new'"
                )

            # Validate rk_type if judge_type is "old"
            if judge_type_lower == "old":
                if rk_type is None:
                    raise ValueError(
                        "rk_type is required when judge_type is 'old'. Must be 'remember' or 'know'"
                    )
                rk_type_lower = rk_type.lower()
                if rk_type_lower not in ["remember", "know"]:
                    raise ValueError(
                        f"Invalid rk_type: {rk_type}. Must be 'remember' or 'know'"
                    )
            else:
                rk_type_lower = None

            # Check if trait is in recognition traits
            if trait not in self.recognition_traits:
                raise ValueError(
                    f"Trait '{trait}' not found in recognition traits list"
                )

            # Check if already submitted
            for existing in self._recognition_judgments[agent_id]:
                if existing["trait"] == trait:
                    raise ValueError(
                        f"Recognition judgment for trait '{trait}' has already been submitted. "
                        f"Current judgment: {existing['judge_type']}"
                    )

            # Determine correctness
            is_correct = False
            if judge_type_lower == "old":
                # Correct if trait was in encoding phase
                is_correct = trait in self._encoding_trait_set
            else:  # judge_type == "new"
                # Correct if trait was NOT in encoding phase
                is_correct = trait not in self._encoding_trait_set

            # Store the judgment
            judgment_data = {
                "trait": trait,
                "judge_type": judge_type_lower,
                "is_correct": is_correct,
                "rk_type": rk_type_lower,
            }
            self._recognition_judgments[agent_id].append(judgment_data)

            # Check if all recognition traits are completed
            completed = len(self._recognition_judgments[agent_id])
            all_completed = completed == len(self.recognition_traits)

            status = "recognition_completed" if all_completed else "submitted"

            # Debug log
            import sys

            print(
                f"[ENV DEBUG] Agent {agent_id} submitted recognition: {trait} = {judge_type_lower} "
                f"(correct: {is_correct}, rk: {rk_type_lower}) "
                f"({completed}/{len(self.recognition_traits)} completed)",
                file=sys.stderr,
            )

            return SubmitRecognitionResponse(
                agent_id=agent_id,
                trait=trait,
                judge_type=judge_type_lower,
                is_correct=is_correct,
                rk_type=rk_type_lower,
                status=status,
            )

    @tool(readonly=True)
    async def get_recognition_status(
        self, agent_id: int
    ) -> GetRecognitionStatusResponse:
        """
        Get recognition phase status for a specific agent.

        :param agent_id: The agent's ID

        :returns: Response containing completed judgments and remaining count. Note: Only returns trait names and judge_type to avoid memory contamination.
        """
        async with self._lock:
            if agent_id not in self.agent_ids:
                raise ValueError(f"Agent ID {agent_id} is not in the experiment")

            # Only return minimal information to avoid memory contamination
            # Don't reveal is_correct or rk_type to prevent agents from using feedback
            completed_judgments = [
                {
                    "trait": j.get("trait", ""),
                    "judge_type": j.get("judge_type", ""),
                }
                for j in self._recognition_judgments[agent_id]
            ]
            remaining_count = len(self.recognition_traits) - len(
                self._recognition_judgments[agent_id]
            )

            return GetRecognitionStatusResponse(
                agent_id=agent_id,
                completed_judgments=completed_judgments,
                remaining_count=remaining_count,
            )

    @tool(readonly=True, kind="statistics")
    async def get_all_results(self) -> dict[str, Any]:
        """
        Get all results for all agents (statistics function).

        :returns: Dictionary containing encoding ratings and recognition judgments for all agents.
        """
        async with self._lock:
            return {
                "encoding_ratings": {
                    agent_id: ratings.copy()
                    for agent_id, ratings in self._encoding_ratings.items()
                },
                "recognition_judgments": {
                    agent_id: judgments.copy()
                    for agent_id, judgments in self._recognition_judgments.items()
                },
            }

    async def init(self, start_datetime: datetime):
        """
        Initialize the environment module.
        """
        await super().init(start_datetime)
        async with self._lock:
            self._encoding_ratings = {agent_id: [] for agent_id in self.agent_ids}
            self._recognition_judgments = {agent_id: [] for agent_id in self.agent_ids}
            self._encoding_trait_set = {t["trait"] for t in self.encoding_traits}
            self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks (1 tick = 1 second) of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.current_datetime = t
            records = [
                {
                    "agent_id": agent_id,
                    "encoding_ratings": [
                        rating.copy() for rating in self._encoding_ratings[agent_id]
                    ],
                    "recognition_judgments": [
                        judgment.copy()
                        for judgment in self._recognition_judgments[agent_id]
                    ],
                    "encoding_completed_count": len(self._encoding_ratings[agent_id]),
                    "recognition_completed_count": len(
                        self._recognition_judgments[agent_id]
                    ),
                }
                for agent_id in self.agent_ids
            ]

        await self._write_agent_state_batch(
            step=self._step_counter,
            t=t,
            records=records,
        )
        self._step_counter += 1

    def get_results(self) -> dict[str, Any]:
        """
        Get all results (synchronous method for result extraction).

        :returns: Dictionary containing encoding ratings and recognition judgments for all agents.
        """
        return {
            "encoding_ratings": {
                agent_id: [rating.copy() for rating in ratings]
                for agent_id, ratings in self._encoding_ratings.items()
            },
            "recognition_judgments": {
                agent_id: [judgment.copy() for judgment in judgments]
                for agent_id, judgments in self._recognition_judgments.items()
            },
        }


__all__ = ["IdentityType", "SelfReferenceEffectEnv"]
